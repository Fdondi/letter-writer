from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.phased_service import (
    _run_background_phase, 
    advance_to_draft, 
    advance_to_refinement,
    get_metadata_field,
    VendorPhaseState
)
from letter_writer.session_store import set_current_request, save_vendor_data
from letter_writer.clients.base import ModelVendor
from letter_writer.generation import MissingCVError
from letter_writer.session_store import load_session_common_data, check_session_exists
from letter_writer.firestore_store import get_user_data
from letter_writer.personal_data_sections import get_models

router = APIRouter()

class InitSessionRequest(BaseModel):
    job_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    vendors: Optional[Dict[str, Any]] = None
    search_result: Optional[str] = None

class BackgroundPhaseRequest(BaseModel):
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None

class DraftPhaseRequest(BaseModel):
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None

class RefinePhaseRequest(BaseModel):
    fancy: Optional[bool] = False
    draft_letter: Optional[str] = None
    feedback_override: Optional[Dict[str, str]] = None
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None

@router.post("/init/")
async def init_session(request: Request, data: InitSessionRequest, session: Session = Depends(get_session)):
    # Check if recovery
    is_recovery = bool(data.job_text or data.metadata or data.vendors)
    session_exists = session.session_key is not None and bool(session)
    
    if is_recovery and not session_exists:
        # Restore logic
        if data.job_text:
            session['job_text'] = data.job_text
        if data.metadata:
            session['metadata'] = data.metadata
        if data.vendors:
            session['vendors'] = data.vendors
        return {
            "status": "ok",
            "session_id": session.session_key,
            "recovered": True,
            "message": "Session restored from client data"
        }
    
    # Normal init
    needs_cv_load = not session_exists or not session.get('cv_text')
    
    if needs_cv_load:
        user_id = None
        user = session.get('user')
        if user:
            user_id = user['id']
            # Load CV from Firestore
            if user_id:
                user_data = get_user_data(user_id, use_cache=True)
                # Assuming get_cv_revisions logic or just get cv_revisions directly
                cv_revisions = user_data.get('cv_revisions', [])
                # Find latest
                if cv_revisions:
                    latest = max(cv_revisions, key=lambda x: x.get('created_at', ''))
                    session['cv_text'] = latest.get('content', '')
    
    if data.job_text:
        session['job_text'] = data.job_text
    if data.metadata:
        # Merge metadata logic
        existing_metadata = session.get('metadata', {})
        existing_metadata.update(data.metadata) # Simplified merge
        session['metadata'] = existing_metadata

    return {
        "status": "ok",
        "session_id": session.session_key,
        "session_exists": session_exists
    }

@router.post("/restore/")
async def restore_session(request: Request, data: InitSessionRequest, session: Session = Depends(get_session)):
    if data.job_text:
        session['job_text'] = data.job_text
    if data.metadata:
        session['metadata'] = data.metadata
    if data.vendors:
        session['vendors'] = data.vendors
    return {
        "status": "ok",
        "session_id": session.session_key,
        "message": "Session restored successfully"
    }

@router.get("/state/")
async def get_session_state(session: Session = Depends(get_session)):
    # Return full session state (excluding potentially huge/sensitive fields if needed, but logic says allow all except CV)
    state = dict(session)
    if 'cv_text' in state:
        del state['cv_text'] # Never send CV back in this endpoint
    return {
        "status": "ok",
        "session_id": session.session_key,
        "session_state": state,
        "has_data": bool(state)
    }

@router.post("/clear/")
async def clear_session(session: Session = Depends(get_session)):
    old_id = session.session_key
    session.clear()
    # Cost flush logic omitted for brevity/simplicity, can add later
    return {
        "status": "ok",
        "old_session_id": old_id,
        "new_session_id": session.session_key, # This might be None until new request? No, middleware generates one.
        "message": "Session cleared successfully"
    }

@router.post("/session/")
async def update_session_common_data(request: Request, data: Dict[str, Any], session: Session = Depends(get_session)):
    # Update common data like job_text, metadata fields
    if "job_text" in data:
        session['job_text'] = data['job_text']
    
    # Update metadata
    if "metadata" not in session:
        session['metadata'] = {}
    if "common" not in session['metadata']:
        session['metadata']['common'] = {}
        
    common = session['metadata']['common']
    # Merge fields from request body into common metadata
    # The frontend sends fields like company_name, job_title directly in body
    fields = ["company_name", "job_title", "location", "language", "salary", "requirements", "competences", "point_of_contact", "additional_user_info", "additional_company_info"]
    for field in fields:
        if field in data:
            common[field] = data[field]
            
    session['metadata']['common'] = common
    return {"status": "ok", "session_id": session.session_key}

@router.post("/background/{vendor}/")
async def background_phase(vendor: str, data: BackgroundPhaseRequest, request: Request, session: Session = Depends(get_session)):
    # Set current request for session_store compatibility (if it uses thread locals)
    set_current_request(request)
    
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check session data availability
    if not session.get('job_text'):
        raise HTTPException(status_code=400, detail="Job text is missing")
    
    # Support overrides
    if data.company_report:
        vendor_state = VendorPhaseState(
            top_docs=data.top_docs or [],
            company_report=data.company_report
        )
        save_vendor_data(session.session_key, vendor, vendor_state)
    else:
        # Run actual background phase
        # Note: _run_background_phase expects session_id. 
        # But we need to make sure session_store.load_session_common_data works with FastAPI request
        # In Django it used request.session. Here load_session_common_data needs adaptation or use explicit data passing.
        # But wait, session_store.py uses set_current_request(request) and then request.session.
        # So as long as request.state.session exists and has dict interface, it *should* work if session_store reads from request.session.
        # However, Django session object has specific methods. My Session class mimics dict.
        # session_store.py:
        # request = get_current_request()
        # session = request.session
        # return session.get("metadata")
        #
        # So it just uses .get(). My Session class has .get(). It should be compatible!
        
        try:
            # Need to pass common_data explicitly or rely on session_store reading it from request
            # Let's verify _run_background_phase signature
            # def _run_background_phase(session_id: str, vendor: ModelVendor, common_data: Dict[str, Any]) -> VendorPhaseState:
            
            # We need to construct common_data from session
            common_data = dict(session)
            # Ensure CV is present
            if not common_data.get('cv_text'):
                raise HTTPException(status_code=400, detail="CV text is missing")
                
            vendor_enum = ModelVendor(vendor)
            vendor_state = _run_background_phase(session.session_key, vendor_enum, common_data)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "ok",
        "company_report": vendor_state.company_report,
        "top_docs": vendor_state.top_docs,
        "cost": vendor_state.cost
    }

@router.post("/draft/{vendor}/")
async def draft_phase(vendor: str, data: DraftPhaseRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        vendor_enum = ModelVendor(vendor)
        # style instructions
        instructions = session.get("style_instructions", "")
        
        state = advance_to_draft(
            session_id=session.session_key,
            vendor=vendor_enum,
            company_report_override=data.company_report,
            top_docs_override=data.top_docs,
            style_instructions=instructions
        )
        return {
            "status": "ok",
            "draft_letter": state.draft_letter,
            "feedback": state.feedback,
            "cost": state.cost
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/refine/{vendor}/")
async def refine_phase(vendor: str, data: RefinePhaseRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        vendor_enum = ModelVendor(vendor)
        state = advance_to_refinement(
            session_id=session.session_key,
            vendor=vendor_enum,
            draft_override=data.draft_letter,
            feedback_override=data.feedback_override,
            company_report_override=data.company_report,
            top_docs_override=data.top_docs,
            fancy=data.fancy
        )
        return {
            "status": "ok",
            "final_letter": state.final_letter,
            "cost": state.cost
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
