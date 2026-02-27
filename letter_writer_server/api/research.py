from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel

from pathlib import Path
from letter_writer.client import get_client, ModelVendor
from letter_writer.generation import extract_job_metadata_no_requirements
from letter_writer.research import perform_company_research, perform_poc_research

router = APIRouter()


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
async def extract_company_metadata(data: ExtractCompanyMetadataRequest):
    """Part 3: Extract company metadata from job text (stateless, no user context)."""
    try:
        ai_client = get_client(ModelVendor.OPENAI)
        trace_dir = Path("trace", "research.company.extraction")
        extraction = extract_job_metadata_no_requirements(data.job_text, ai_client, trace_dir=trace_dir)
        return {"status": "ok", "extraction": extraction}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Company extraction failed: {e}")


@router.post("/company/")
async def research_company(data: ResearchCompanyRequest):
    """Part 4: Company background research (cache → vector search → new). Stateless."""
    models = data.models or ["openai"]
    company_name = (data.company_name or "").strip()

    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")

    try:
        result = perform_company_research(
            company_name=company_name,
            models=models,
            job_text=data.job_text or "",
            additional_company_info=data.additional_company_info or "",
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
async def research_poc(data: ResearchPocRequest):
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
