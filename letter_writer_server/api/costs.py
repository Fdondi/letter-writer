from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.cost_tracker import (
    get_cost_summary,
    flush_costs_to_bigquery,
    get_user_monthly_cost,
    get_global_monthly_cost,
    get_user_daily_costs,
    get_all_model_pricing
)

router = APIRouter()

@router.get("/summary/")
async def get_summary():
    try:
        return get_cost_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/flush/")
async def flush_costs():
    try:
        return flush_costs_to_bigquery(reset_after_flush=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/user/")
async def get_user_costs(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    months = int(request.query_params.get("months", 1))
    
    try:
        result = get_user_monthly_cost(user['id'], months_back=months)
        pending = get_cost_summary()
        pending_cost = pending.get("pending_by_user", {}).get(user['id'], 0)
        
        result["total_cost"] = result.get("total_cost", 0) + pending_cost
        result["pending_cost"] = pending_cost
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/global/")
async def get_global_costs(request: Request):
    months = int(request.query_params.get("months", 1))
    try:
        return get_global_monthly_cost(months_back=months)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/daily/")
async def get_daily_costs(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    months = int(request.query_params.get("months", 1))
    try:
        return get_user_daily_costs(user['id'], months_back=months)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/")
async def get_models_pricing():
    try:
        return get_all_model_pricing()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
