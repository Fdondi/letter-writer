from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional
from pydantic import BaseModel

from pathlib import Path
from letter_writer.client import get_client, ModelVendor
from letter_writer.generation import extract_job_metadata_no_requirements, resolve_search_instructions
from letter_writer.research import perform_company_research, perform_poc_research
from letter_writer.firestore_store import get_user_data
from letter_writer_server.core.session import Session, get_session
from letter_writer_server.api.cost_utils import check_spending_limits
from letter_writer.cost_tracker import track_api_cost

router = APIRouter()

def _reset_client_counters(client) -> None:
    client.total_cost = 0.0
    client.total_input_tokens = 0
    client.total_output_tokens = 0
    if hasattr(client, "total_cached_tokens"):
        client.total_cached_tokens = 0
    if hasattr(client, "total_search_queries"):
        client.total_search_queries = 0


def _track_and_reset_client_cost(*, user_id: str, phase: str, vendor: str, client) -> None:
    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    if cost <= 0:
        _reset_client_counters(client)
        return
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    cached_tokens = int(getattr(client, "total_cached_tokens", 0) or 0)
    search_queries = int(getattr(client, "total_search_queries", 0) or 0)
    track_api_cost(
        user_id=user_id,
        phase=phase,
        vendor=vendor,
        cost=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        search_queries=search_queries if search_queries else None,
        cached_tokens=cached_tokens if cached_tokens else None,
    )
    _reset_client_counters(client)


class ExtractCompanyMetadataRequest(BaseModel):
    job_text: str


class ResearchCompanyRequest(BaseModel):
    company_name: str
    job_text: Optional[str] = ""
    models: Optional[List[str]] = None
    additional_company_info: Optional[str] = ""


class ResearchPocRequest(BaseModel):
    poc_name: str
    company_name: str
    job_text: Optional[str] = ""
    models: Optional[List[str]] = None


@router.post("/company/extract/")
async def extract_company_metadata(data: ExtractCompanyMetadataRequest, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    """Part 3: Extract company metadata from job text (stateless, no user context)."""
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        user_id = (session.get("user") or {}).get("id") or "anonymous"
        ai_client = get_client(ModelVendor.OPENAI)
        _reset_client_counters(ai_client)
        trace_dir = Path("trace", "research.company.extraction")
        extraction = extract_job_metadata_no_requirements(data.job_text, ai_client, trace_dir=trace_dir)
        _track_and_reset_client_cost(user_id=user_id, phase="extract", vendor=ModelVendor.OPENAI.value, client=ai_client)
        return {"status": "ok", "extraction": extraction}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Company extraction failed: {e}")


@router.post("/company/")
async def research_company(data: ResearchCompanyRequest, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    """Part 4: Company background research (cache → vector search → new). Stateless."""
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    models = data.models or ["openai"]
    company_name = (data.company_name or "").strip()

    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")

    try:
        user_data = None
        user = session.get("user")
        if user:
            user_data = get_user_data(user["id"], use_cache=True)
        search_instructions = resolve_search_instructions(
            session.get("search_instructions", ""),
            user_data or {},
        )
        result = perform_company_research(
            company_name=company_name,
            models=models,
            job_text=data.job_text or "",
            additional_company_info=data.additional_company_info or "",
            search_instructions=search_instructions,
        )
        return {
            "status": "ok",
            "company_name": company_name,
            "results": result["results"],
            "source": result["source"],
            "resolved_name": result.get("resolved_name", company_name),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/poc/")
async def research_poc(data: ResearchPocRequest, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    models = data.models or ["openai"]
    try:
        results = perform_poc_research(
            poc_name=data.poc_name,
            models=models,
            company_name=data.company_name,
            job_text=data.job_text
        )
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
