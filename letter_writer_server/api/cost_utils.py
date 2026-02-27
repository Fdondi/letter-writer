import logging
import time
from typing import Any, Dict

from letter_writer.cost_tracker import get_cost_summary, get_user_monthly_cost

logger = logging.getLogger(__name__)
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
