import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, HTTPException

from letter_writer.cost_tracker import get_cost_summary, get_user_monthly_cost, get_user_today_cost
from letter_writer_server.core.session import Session, get_session, require_auth

logger = logging.getLogger(__name__)

# Spending limits — override via env vars for future tier support.
MONTHLY_LIMIT_USD: float = float(os.getenv("USER_MONTHLY_LIMIT_USD", "10.0"))
DAILY_LIMIT_USD: float = float(os.getenv("USER_DAILY_LIMIT_USD", "2.0"))

COST_CACHE_KEY = "_user_monthly_cost_cache"
COST_CACHE_TTL_SECONDS = 60.0


class CostTrackingUnavailable(Exception):
    """Raised when persisted cost analytics cannot be read (e.g. BigQuery unreachable)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _require_cost_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("error"):
        raise CostTrackingUnavailable(str(result["error"]))
    if result.get("cost_available") is False:
        raise CostTrackingUnavailable(str(result.get("error") or "Cost analytics unavailable"))
    return result


def _get_bigquery_user_monthly_cost(user_id: str, months_back: int = 1) -> float:
    result = _require_cost_result(get_user_monthly_cost(user_id, months_back=months_back))
    return float(result.get("total_cost", 0.0) or 0.0)


def _get_user_monthly_cost_with_pending(
    user_id: str, session: Any, months_back: int = 1
) -> Tuple[float, Optional[str]]:
    """Return (monthly_total, error_message). error_message is set when BigQuery is unavailable."""
    pending = get_cost_summary()
    pending_cost = pending.get("pending_by_user", {}).get(user_id, 0.0)
    pending_cost = float(pending_cost or 0.0)

    now = time.time()
    cache = session.get(COST_CACHE_KEY) if session else None
    if not isinstance(cache, dict):
        cache = {}

    cached_base = float(cache.get("base_total", 0.0) or 0.0)
    cached_at = float(cache.get("fetched_at", 0.0) or 0.0)
    last_pending = float(cache.get("last_pending", 0.0) or 0.0)
    cached_error = cache.get("last_error")

    should_refresh = (
        cached_at <= 0
        or (now - cached_at) > COST_CACHE_TTL_SECONDS
        or pending_cost < (last_pending - 1e-12)
    )

    fetch_error: Optional[str] = None
    if should_refresh:
        try:
            cached_base = _get_bigquery_user_monthly_cost(user_id, months_back=months_back)
            cached_at = now
            cached_error = None
        except CostTrackingUnavailable as exc:
            fetch_error = exc.message
            cached_error = exc.message
            # Do not update cached_at — retry on next request after TTL

    if session is not None:
        session[COST_CACHE_KEY] = {
            "base_total": cached_base,
            "fetched_at": cached_at,
            "last_pending": pending_cost,
            "last_error": cached_error,
        }

    bq_error = fetch_error or (cached_error if not should_refresh else None)
    flush_error = pending.get("last_bigquery_error")
    combined_error = bq_error or flush_error

    if combined_error:
        return pending_cost, combined_error

    return cached_base + pending_cost, None


def with_user_monthly_cost(payload: Dict[str, Any], session: Any, months_back: int = 1) -> Dict[str, Any]:
    """Attach latest monthly user cost to operation responses when possible."""
    user = session.get("user") if session else None
    user_id = (user or {}).get("id")
    if not user_id:
        return payload
    try:
        monthly, cost_error = _get_user_monthly_cost_with_pending(user_id, session, months_back=months_back)
        if cost_error:
            payload["cost_tracking_error"] = cost_error
        else:
            payload["user_monthly_cost"] = monthly
    except Exception as exc:
        logger.warning("Failed to append user_monthly_cost for user=%s: %s", user_id, exc)
        payload["cost_tracking_error"] = str(exc)
    return payload


async def check_spending_limits(
    user: dict = Depends(require_auth),
    session: Session = Depends(get_session),
) -> None:
    """FastAPI dependency: raises HTTP 402 if the user has exceeded their daily or monthly limit."""
    user_id = user["id"]
    try:
        monthly, cost_error = _get_user_monthly_cost_with_pending(user_id, session)
        if cost_error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Cannot verify spending limits: cost analytics are unavailable "
                    f"({cost_error}). Check container network access to Google APIs."
                ),
            )
        if monthly >= MONTHLY_LIMIT_USD:
            raise HTTPException(
                status_code=402,
                detail=f"Monthly spending limit of ${MONTHLY_LIMIT_USD:.2f} reached. "
                       "Contact support to increase your limit.",
            )
        daily = get_user_today_cost(user_id)
        if daily >= DAILY_LIMIT_USD:
            raise HTTPException(
                status_code=402,
                detail=f"Daily spending limit of ${DAILY_LIMIT_USD:.2f} reached. "
                       "Limit resets at midnight UTC.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spending limit check failed for user=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Cannot verify spending limits: {exc}",
        ) from exc
