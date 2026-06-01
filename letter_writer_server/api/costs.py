from fastapi import APIRouter, Request, HTTPException, Depends, Query
from typing import Dict, Any

from letter_writer_server.core.session import Session, get_session
from letter_writer.cost_tracker import (
    get_cost_summary,
    flush_costs_to_bigquery,
    get_user_monthly_cost,
    get_global_monthly_cost,
    get_user_daily_costs,
    get_all_model_pricing,
)
from letter_writer_server.api.cost_utils import CostTrackingUnavailable, _require_cost_result

router = APIRouter()


def _parse_months(request: Request) -> int:
    try:
        months = int(request.query_params.get("months", 1))
        return max(1, min(months, 24))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="months must be an integer")


def _raise_cost_http(exc: CostTrackingUnavailable) -> None:
    raise HTTPException(
        status_code=503,
        detail=f"Cost analytics unavailable: {exc.message}",
    ) from exc


@router.get("/summary/")
async def get_summary(session: Session = Depends(get_session)):
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return get_cost_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/flush/")
async def flush_costs(session: Session = Depends(get_session)):
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        result = flush_costs_to_bigquery(reset_after_flush=True)
        if result.get("status") == "error":
            raise HTTPException(
                status_code=503,
                detail=result.get("error") or "BigQuery flush failed",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/user/")
async def get_user_costs(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    months = _parse_months(request)

    try:
        result = _require_cost_result(get_user_monthly_cost(user['id'], months_back=months))
        pending = get_cost_summary()
        pending_cost = pending.get("pending_by_user", {}).get(user['id'], 0)

        result["total_cost"] = result.get("total_cost", 0) + pending_cost
        result["pending_cost"] = pending_cost
        if pending.get("last_bigquery_error"):
            result["last_bigquery_flush_error"] = pending["last_bigquery_error"]
        return result
    except CostTrackingUnavailable as exc:
        _raise_cost_http(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/global/")
async def get_global_costs(request: Request, session: Session = Depends(get_session)):
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    months = _parse_months(request)
    try:
        return _require_cost_result(get_global_monthly_cost(months_back=months))
    except CostTrackingUnavailable as exc:
        _raise_cost_http(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/daily/")
async def get_daily_costs(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    months = _parse_months(request)
    try:
        return _require_cost_result(get_user_daily_costs(user['id'], months_back=months))
    except CostTrackingUnavailable as exc:
        _raise_cost_http(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/")
async def get_models_pricing(supports_search: bool = Query(False)):
    try:
        return get_all_model_pricing(search_only=supports_search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
