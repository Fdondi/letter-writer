import logging
import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Any, Dict, List, Optional, cast
from pydantic import BaseModel

from letter_writer.agentic_worker import remove_agentic_live
from letter_writer_server.core.session import (
    Session,
    get_session,
    require_auth,
)
from letter_writer_server.api.cost_utils import check_spending_limits
from letter_writer.feedback_checks import (
    PHASED_FEEDBACK_CATEGORY_KEYS,
    get_phased_feedback_checker_prompts,
    run_suggest_additional_feedback_context,
)
from letter_writer.instructions import get_structure_instructions as get_default_structure_instructions
from letter_writer.clients.base import ModelVendor
from letter_writer_server.api.cost_utils import with_user_monthly_cost
from letter_writer.phased_service import (
    _run_background_phase,
    advance_to_plan,
    advance_to_draft,
    advance_to_refinement,
    get_effective_additional_user_info,
    get_metadata_field,
    VendorPhaseState,
    _reset_client_counters,
    _update_cost,
)
from letter_writer.client import get_client
from letter_writer.session_store import set_current_request, save_vendor_data, load_vendor_data, log_user_input_event
from letter_writer.firestore_store import get_user_data
from letter_writer.personal_data_sections import (
    cv_text_with_extra_info,
    get_structure_instructions as get_user_structure_instructions,
)
from letter_writer.typed_shapes import TopDocument

router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)


class InitSessionRequest(BaseModel):
    job_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    vendors: Optional[Dict[str, Any]] = None
    search_result: Optional[str] = None

class BackgroundPhaseRequest(BaseModel):
    company_report: Optional[str] = None


class DraftPhaseRequest(BaseModel):
    company_report: Optional[str] = None
    letter_plan: Optional[str] = None


class PlanPhaseRequest(BaseModel):
    company_report: Optional[str] = None


class RefinePhaseRequest(BaseModel):
    fancy: Optional[bool] = False
    draft_letter: Optional[str] = None
    feedback_override: Optional[Dict[str, Any]] = None
    company_report: Optional[str] = None


class FeedbackRequestContextBody(BaseModel):
    """Re-run context extraction for one feedback item with the same materials as the original checker."""

    category: str
    item_id: str


@router.post("/init/")
def init_session(request: Request, data: InitSessionRequest, session: Session = Depends(get_session)):
    set_current_request(request)
    log_user_input_event("phases.init", data.dict(exclude_none=True))
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
                    base_cv = latest.get('content', '')
                    session['cv_text'] = cv_text_with_extra_info(base_cv, user_data)
    
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
def restore_session(request: Request, data: InitSessionRequest, session: Session = Depends(get_session)):
    set_current_request(request)
    log_user_input_event("phases.restore", data.dict(exclude_none=True))
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


class RestoreFromBackupRequest(BaseModel):
    filename: str


@router.get("/backups/")
def list_backups(limit: int = 100):
    from letter_writer_server.core.session_backup import list_session_backups

    safe_limit = max(1, min(int(limit or 100), 500))
    backups = list_session_backups(limit=safe_limit)
    return {"status": "ok", "backups": backups}


@router.post("/restore-from-backup/")
def restore_from_backup(
    request: Request,
    data: RestoreFromBackupRequest,
    session: Session = Depends(get_session),
):
    """Load a host backup file into the current cookie session and return full state."""
    from letter_writer_server.core.session_backup import (
        apply_backup_to_session_dict,
        load_backup_envelope,
    )

    set_current_request(request)
    log_user_input_event("phases.restore_from_backup", {"filename": data.filename})

    user = session.get("user") or {}
    current_user_id = str(user["id"]) if isinstance(user, dict) and user.get("id") is not None else None

    try:
        envelope = load_backup_envelope(data.filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Backup not found: {data.filename}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to load backup %s: %s", data.filename, e)
        raise HTTPException(status_code=400, detail=f"Failed to read backup: {e}")

    try:
        # Session is a dict subclass; apply mutates it in place.
        session_state = apply_backup_to_session_dict(session, envelope, current_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Ensure dirty tracking so middleware persists the restored work keys.
    for key in list(session_state.keys()):
        if key in session:
            session[key] = session[key]

    # Never send CV text to the browser; it stays in the server session only.
    response_state = dict(session_state)
    response_state.pop("cv_text", None)

    return {
        "status": "ok",
        "session_id": session.session_key,
        "filename": data.filename,
        "message": "Session restored from host backup",
        "session_state": response_state,
    }


@router.get("/state/")
def get_session_state(session: Session = Depends(get_session)):
    # Return full session state (excluding potentially huge/sensitive fields if needed, but logic says allow all except CV)
    state = dict(session)
    if 'cv_text' in state:
        del state['cv_text'] # Never send CV back in this endpoint
    # Strategic letter plan is returned only from POST /plan/ and sent once in POST /draft/; omit from this snapshot.
    vendors = state.get("vendors")
    if isinstance(vendors, dict):
        redacted_vendors = {}
        for k, v in vendors.items():
            if isinstance(v, dict):
                vc = dict(v)
                vc.pop("letter_plan", None)
                redacted_vendors[k] = vc
            else:
                redacted_vendors[k] = v
        state["vendors"] = redacted_vendors
    return {
        "status": "ok",
        "session_id": session.session_key,
        "session_state": state,
        "has_data": bool(state)
    }

@router.post("/clear/")
def clear_session(session: Session = Depends(get_session)):
    old_id = session.session_key
    user = session.get("user")
    auth_time = session.get("auth_time")
    if old_id:
        remove_agentic_live(old_id)
    session.clear()
    if user:
        session["user"] = user
        # require_auth treats missing auth_time as 0 (epoch), which always fails the 24h check.
        if auth_time is not None:
            session["auth_time"] = auth_time
    # Rotate to a brand-new session id while keeping authenticated user context.
    session.session_key = secrets.token_urlsafe(32)
    return {
        "status": "ok",
        "old_session_id": old_id,
        "new_session_id": session.session_key,
        "message": "Session cleared successfully"
    }

@router.post("/session/")
def update_session_common_data(request: Request, data: Dict[str, Any], session: Session = Depends(get_session)):
    set_current_request(request)
    log_user_input_event("phases.session_update", data)
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
    fields = ["company_name", "job_title", "location", "language", "salary", "requirements", "competences", "hire_problem", "point_of_contact", "additional_user_info", "additional_company_info"]
    for field in fields:
        if field in data:
            common[field] = data[field]

    if "structure_instructions" in data and isinstance(data.get("structure_instructions"), str):
        session["structure_instructions"] = data["structure_instructions"]

    if "top_docs" in data:
        td = data.get("top_docs")
        session["selected_top_docs"] = td if isinstance(td, list) else []
            
    session['metadata']['common'] = common
    return {"status": "ok", "session_id": session.session_key}

@router.post("/background/{vendor}/")
def background_phase(vendor: str, data: BackgroundPhaseRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    # Set current request for session_store compatibility (if it uses thread locals)
    set_current_request(request)
    log_user_input_event("phases.background", {"vendor": vendor, "payload": data.dict(exclude_none=True)})
    
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check session data availability
    if not session.get('job_text'):
        raise HTTPException(status_code=400, detail="Job text is missing")
    session_key = session.session_key
    if not session_key:
        raise HTTPException(status_code=400, detail="No session")
    
    # Support overrides: inject precomputed company report; example letters come from session selected_top_docs.
    if data.company_report:
        sel = session.get("selected_top_docs") or []
        vendor_state = VendorPhaseState(
            top_docs=cast(List[TopDocument], list(sel)),
            company_report=data.company_report
        )
        save_vendor_data(session_key, vendor, vendor_state)
    else:
        # Run actual background phase
        # Note: _run_background_phase expects session_id. 
        # But we need to make sure session_store.load_session_common_data works with FastAPI request
        # Historically this used request.session in a Django code path.
        # But wait, session_store.py uses set_current_request(request) and then request.session.
        # So as long as request.state.session exists and has dict interface, it *should* work if session_store reads from request.session.
        # The previous session object had framework-specific methods; our Session class mimics dict.
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
            user_id = (user or {}).get("id") or "anonymous"
            vendor_state = _run_background_phase(session_key, vendor_enum, common_data, user_id=user_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return with_user_monthly_cost({
        "status": "ok",
        "company_report": vendor_state.company_report,
        "top_docs": vendor_state.top_docs,
        "cost": vendor_state.cost
    }, session)


@router.post("/plan/{vendor}/")
def plan_phase(vendor: str, data: PlanPhaseRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.plan", {"vendor": vendor, "payload": data.dict(exclude_none=True)})
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        vendor_enum = ModelVendor(vendor)
        structure = (session.get("structure_instructions") or "").strip()
        if not structure:
            uid = (user or {}).get("id")
            if uid:
                user_data = get_user_data(uid, use_cache=True) or {}
                structure = get_user_structure_instructions(user_data)
        if not structure:
            structure = get_default_structure_instructions()
        user_id = (user or {}).get("id") or "anonymous"
        state = advance_to_plan(
            session_id=session.session_key,
            vendor=vendor_enum,
            company_report_override=data.company_report,
            structure_instructions=structure,
            user_id=user_id,
        )
        return with_user_monthly_cost(
            {
                "status": "ok",
                "letter_plan": state.letter_plan,
                "cost": state.cost,
            },
            session,
        )
    except Exception as e:
        logger.exception("phases.plan failed (vendor=%s)", vendor)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/draft/{vendor}/")
def draft_phase(vendor: str, data: DraftPhaseRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.draft", {"vendor": vendor, "payload": data.dict(exclude_none=True)})
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        vendor_enum = ModelVendor(vendor)
        # style instructions
        instructions = session.get("style_instructions", "")
        user_id = (user or {}).get("id") or "anonymous"
        state = advance_to_draft(
            session_id=session.session_key,
            vendor=vendor_enum,
            company_report_override=data.company_report,
            style_instructions=instructions,
            letter_plan_override=data.letter_plan,
            user_id=user_id,
        )
        return with_user_monthly_cost({
            "status": "ok",
            "draft_letter": state.draft_letter,
            "known_weaknesses": state.known_weaknesses,
            "feedback": state.feedback,
            "cost": state.cost
        }, session)
    except ValueError as e:
        msg = str(e)
        if "letter plan" in msg.lower():
            raise HTTPException(status_code=400, detail=msg) from e
        raise HTTPException(status_code=500, detail=msg) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/refine/{vendor}/")
def refine_phase(vendor: str, data: RefinePhaseRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.refine", {"vendor": vendor, "payload": data.dict(exclude_none=True)})
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        vendor_enum = ModelVendor(vendor)
        user_id = (user or {}).get("id") or "anonymous"
        state = advance_to_refinement(
            session_id=session.session_key,
            vendor=vendor_enum,
            draft_override=data.draft_letter,
            feedback_override=data.feedback_override,
            company_report_override=data.company_report,
            fancy=data.fancy,
            style_instructions=session.get("style_instructions") or "",
            user_id=user_id,
        )
        return with_user_monthly_cost({
            "status": "ok",
            "final_letter": state.final_letter,
            "cost": state.cost
        }, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback/request-context/{vendor}/")
def feedback_request_context(
    vendor: str,
    data: FeedbackRequestContextBody,
    request: Request,
    session: Session = Depends(get_session),
    _limit: None = Depends(check_spending_limits),
):
    """LLM pass: same checker context as draft feedback, to suggest context_field lines the first pass missed."""
    set_current_request(request)
    log_user_input_event(
        "phases.feedback_request_context",
        {"vendor": vendor, "payload": data.dict(exclude_none=True)},
    )
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    cat = (data.category or "").strip().lower()
    if cat not in PHASED_FEEDBACK_CATEGORY_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of {PHASED_FEEDBACK_CATEGORY_KEYS}",
        )

    session_key = session.session_key
    if not session_key:
        raise HTTPException(status_code=400, detail="No session")

    try:
        vendor_enum = ModelVendor(vendor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    vstate = load_vendor_data(session_key, vendor)
    if vstate is None:
        raise HTTPException(status_code=404, detail="No saved data for this vendor")

    draft = (vstate.draft_letter or "").strip()
    if not draft:
        raise HTTPException(status_code=400, detail="Draft letter is missing; run draft first")

    fb = (vstate.feedback or {}).get(cat)
    if not isinstance(fb, list):
        raise HTTPException(status_code=400, detail="Invalid feedback for this category")

    item = next(
        (x for x in fb if isinstance(x, dict) and str(x.get("id")) == str(data.item_id)),
        None,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found")

    obs = str(item.get("observation") or "").strip()
    if not obs:
        raise HTTPException(status_code=400, detail="Item has no observation text")

    ctx_items: List[Any] = []
    cf = item.get("context_field")
    if isinstance(cf, dict) and isinstance(cf.get("items"), list):
        ctx_items = cf.get("items") or []

    ai_client = get_client(vendor_enum)
    _reset_client_counters(ai_client)
    try:
        metadata = session.get("metadata") or {}
        uid = (user or {}).get("id") if user else None
        top_docs = vstate.top_docs or []
        prompts = get_phased_feedback_checker_prompts(
            cat,
            letter=draft,
            style_instructions=session.get("style_instructions") or "",
            cv_text=session.get("cv_text") or "",
            additional_user_info=get_effective_additional_user_info(metadata, vendor_enum, uid),
            company_report=vstate.company_report or "",
            job_text=session.get("job_text") or "",
            hire_problem=str(get_metadata_field(metadata, vendor_enum, "hire_problem", "") or ""),
            top_docs=top_docs if cat in ("user_fit", "human") else None,
        )
        if prompts is None:
            raise ValueError(
                "The human-dimension checker has no reference materials (no AI letter examples with revision history)."
            )
        system, base_prompt = prompts
        new_items = run_suggest_additional_feedback_context(
            ai_client,
            cat,
            obs,
            ctx_items,
            system,
            base_prompt,
            top_docs=top_docs if cat in ("user_fit", "human") else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    user_id = (user or {}).get("id") or "anonymous"
    _update_cost(vstate, ai_client, phase="feedback", user_id=user_id, vendor_str=vendor_enum.value)
    save_vendor_data(session_key, vendor, vstate)

    return with_user_monthly_cost(
        {"status": "ok", "items": new_items, "cost": vstate.cost},
        session,
    )
