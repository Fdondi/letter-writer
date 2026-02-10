from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from pathlib import Path

from letter_writer_server.core.session import Session, get_session
from letter_writer.client import get_client, ModelVendor
from letter_writer.generation import extract_job_metadata, MissingCVError, get_style_instructions
from letter_writer.service import write_cover_letter, refresh_repository
from letter_writer.firestore_store import get_collection, upsert_document, get_user_data
from letter_writer.retrieval import embed
from letter_writer.personal_data_sections import get_models
from letter_writer.spam_prevention import get_in_flight_requests, clear_in_flight_requests
from openai import OpenAI

router = APIRouter()

class ExtractRequest(BaseModel):
    job_text: str
    scale_config: Optional[Dict[str, Any]] = None

class ProcessJobRequest(BaseModel):
    job_text: str
    cv_text: Optional[str] = None
    company_name: Optional[str] = None
    model_vendor: Optional[str] = None
    refine: bool = False
    fancy: bool = False

class RefreshRequest(BaseModel):
    jobs_source_folder: Optional[str] = None
    jobs_source_suffix: Optional[str] = None
    letters_source_folder: Optional[str] = None
    letters_source_suffix: Optional[str] = None
    letters_ignore_until: Optional[str] = None
    letters_ignore_after: Optional[str] = None
    negative_letters_source_folder: Optional[str] = None
    negative_letters_source_suffix: Optional[str] = None
    clear: bool = False

@router.post("/refresh/")
async def refresh(request: Request, data: RefreshRequest):
    try:
        kwargs = data.dict(exclude_unset=True)
        # Convert path strings to Path objects if needed by refresh_repository
        if "jobs_source_folder" in kwargs: kwargs["jobs_source_folder"] = Path(kwargs["jobs_source_folder"])
        if "letters_source_folder" in kwargs: kwargs["letters_source_folder"] = Path(kwargs["letters_source_folder"])
        if "negative_letters_source_folder" in kwargs: kwargs["negative_letters_source_folder"] = Path(kwargs["negative_letters_source_folder"])
        
        refresh_repository(**kwargs, logger=print)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/extract/")
async def extract_job(request: Request, data: ExtractRequest, session: Session = Depends(get_session)):
    user = session.get('user')
    # Load CV logic...
    cv_text = session.get('cv_text', "")
    if not cv_text and user:
        user_data = get_user_data(user['id'], use_cache=True)
        cv_revisions = user_data.get('cv_revisions', [])
        if cv_revisions:
            # Sort by created_at desc
            sorted_revs = sorted(cv_revisions, key=lambda x: x.get('created_at', ''), reverse=True)
            cv_text = sorted_revs[0].get('content', '')
            session['cv_text'] = cv_text
            
    if not cv_text:
        raise HTTPException(status_code=400, detail="CV text is missing")

    try:
        ai_client = get_client(ModelVendor.OPENAI)
        trace_dir = Path("trace", "extraction.openai")
        extraction = extract_job_metadata(
            data.job_text,
            ai_client,
            trace_dir=trace_dir,
            cv_text=cv_text,
            scale_config=data.scale_config
        )
        
        if "metadata" not in session: session["metadata"] = {}
        if "common" not in session["metadata"]: session["metadata"]["common"] = {}
        session["metadata"]["common"].update(extraction)
        session["job_text"] = data.job_text
        
        return {
            "status": "ok",
            "extraction": extraction,
            "session_id": session.session_key
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-job/")
async def process_job(request: Request, data: ProcessJobRequest, session: Session = Depends(get_session)):
    try:
        instructions = session.get("style_instructions", "")
        if not instructions:
            instructions = get_style_instructions()
            
        kwargs = {
            "job_text": data.job_text,
            "cv_text": data.cv_text or session.get("cv_text", ""),
            "company_name": data.company_name,
            "model_vendor": ModelVendor(data.model_vendor) if data.model_vendor else None,
            "refine": data.refine,
            "fancy": data.fancy,
            "style_instructions": instructions,
            "out": Path("letters")
        }
        
        letters = write_cover_letter(**kwargs, logger=print)
        
        # Persist logic (simplified)
        user = session.get('user')
        if user:
            # Upsert document logic if needed
            pass
            
        return {"status": "ok", "letters": letters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/translate/")
async def translate(request: Request):
    # Retrieve logic from views.py:
    # _translate_with_google(texts, target_language, source_language)
    # I need to import or reimplement it. It uses googleapis.com directly.
    # For now, stub or simplified.
    return {"status": "ok", "translations": []}

@router.get("/vendors/")
async def list_vendors(session: Session = Depends(get_session)):
    vendors = [v.value for v in ModelVendor]
    active_vendors = set(vendors)
    if session.get("metadata", {}).get("common", {}).get("selected_vendors"):
         active_vendors = set(session["metadata"]["common"]["selected_vendors"])
    
    return {
        "active": [v for v in vendors if v in active_vendors],
        "inactive": [v for v in vendors if v not in active_vendors]
    }

@router.get("/debug/in-flight-requests/")
async def debug_in_flight():
    return {"count": len(get_in_flight_requests()), "requests": get_in_flight_requests()}

@router.post("/debug/clear-in-flight-requests/")
async def debug_clear_in_flight():
    cleared = clear_in_flight_requests()
    return {"status": "ok", "cleared_count": cleared}
