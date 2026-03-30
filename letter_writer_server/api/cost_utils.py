import logging
import os
import time
from typing import Any, Dict

from fastapi import Depends, HTTPException

from letter_writer.cost_tracker import get_cost_summary, get_user_monthly_cost, get_user_today_cost
from letter_writer_server.core.session import Session, get_session, require_auth

logger = logging.getLogger(__name__)

# Spending limits — override via env vars for future tier support.
MONTHLY_LIMIT_USD: float = float(os.getenv("USER_MONTHLY_LIMIT_USD", "10.0"))
DAILY_LIMIT_USD: float = float(os.getenv("USER_DAILY_LIMIT_USD", "2.0"))

COST_CACHE_KEY = "_user_monthly_cost_cache"
COST_CACHE_TTL_SECONDS = 60.0


def _get_bigquery_user_monthly_cost(user_id: str, months_back: int = 1) -> float:
    result = get_user_monthly_cost(user_id, months_back=months_back)
    return float(result.get("total_cost", 0.0) or 0.0)


def _get_user_monthly_cost_with_pending(user_id: str, session: Any, months_back: int = 1) -> float:
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

    should_refresh = (
        cached_at <= 0
        or (now - cached_at) > COST_CACHE_TTL_SECONDS
        or pending_cost < (last_pending - 1e-12)
    )
    if should_refresh:
        cached_base = _get_bigquery_user_monthly_cost(user_id, months_back=months_back)
        cached_at = now

    if session is not None:
        session[COST_CACHE_KEY] = {
            "base_total": cached_base,
            "fetched_at": cached_at,
            "last_pending": pending_cost,
        }

    return cached_base + pending_cost


def with_user_monthly_cost(payload: Dict[str, Any], session: Any, months_back: int = 1) -> Dict[str, Any]:
    """Attach latest monthly user cost to operation responses when possible."""
    user = session.get("user") if session else None
    user_id = (user or {}).get("id")
    if not user_id:
        return payload
    try:
        payload["user_monthly_cost"] = _get_user_monthly_cost_with_pending(user_id, session, months_back=months_back)
    except Exception as exc:
        logger.warning("Failed to append user_monthly_cost for user=%s: %s", user_id, exc)
    return payload


async def check_spending_limits(
    user: dict = Depends(require_auth),
    session: Session = Depends(get_session),
) -> None:
    """FastAPI dependency: raises HTTP 402 if the user has exceeded their daily or monthly limit."""
    user_id = user["id"]
    try:
        monthly = _get_user_monthly_cost_with_pending(user_id, session)
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
        # Don't block the user if the limit check itself fails — log and continue.
        logger.warning("Spending limit check failed for user=%s: %s", user_id, exc)
