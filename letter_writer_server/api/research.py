from fastapi import APIRouter, Request, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.research import perform_company_research, perform_poc_research
from letter_writer.firestore_store import get_user_data
from letter_writer.personal_data_sections import get_background_models

router = APIRouter()

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

@router.post("/company/")
async def research_company(request: Request, data: ResearchCompanyRequest, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_id = user['id']
    models = data.models
    
    if not models:
        user_data = get_user_data(user_id, use_cache=True)
        models = get_background_models(user_data)

    try:
        results = perform_company_research(
            company_name=data.company_name,
            user_id=user_id,
            models=models,
            job_text=data.job_text,
            additional_company_info=data.additional_company_info
        )
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/poc/")
async def research_poc(request: Request, data: ResearchPocRequest, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_id = user['id']
    models = data.models
    
    if not models:
        user_data = get_user_data(user_id, use_cache=True)
        models = get_background_models(user_data)

    try:
        results = perform_poc_research(
            poc_name=data.poc_name,
            user_id=user_id,
            models=models,
            company_name=data.company_name,
            job_text=data.job_text
        )
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
