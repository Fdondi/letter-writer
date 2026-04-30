import copy
import logging
import random
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, cast
from pydantic import BaseModel, Field

from letter_writer_server.core.session import (
    Session,
    get_session,
    require_auth,
    get_agentic_last_poll_at_from_storage,
    load_session_from_storage,
    save_session_to_storage,
    save_agentic_state_to_storage,
    save_agentic_topic_slice_to_storage,
    persist_agentic_last_poll_at,
    try_acquire_agentic_lock,
    release_agentic_lock,
)
from letter_writer_server.api.cost_utils import check_spending_limits
from letter_writer.generation import (
    AGENTIC_TOPIC_KEYS,
    get_agentic_topic_context,
    get_style_instructions,
    PHASED_FEEDBACK_CATEGORY_KEYS,
    _phased_feedback_checker_accuracy_prompts,
    _phased_feedback_checker_company_fit_prompts,
    _phased_feedback_checker_human_prompts,
    _phased_feedback_checker_instruction_prompts,
    _phased_feedback_checker_precision_prompts,
    _phased_feedback_checker_user_fit_prompts,
    _run_suggest_additional_feedback_context,
)
from letter_writer.clients.base import ModelVendor
from letter_writer_server.api.cost_utils import with_user_monthly_cost
from letter_writer.phased_service import (
    _run_background_phase,
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
from letter_writer.clients.base import ModelVendor
from letter_writer.generation import MissingCVError
from letter_writer.session_store import load_session_common_data, check_session_exists
from letter_writer.firestore_store import get_user_data
from letter_writer.personal_data_sections import cv_text_with_extra_info, get_models, get_agentic_draft_model
from letter_writer.typed_shapes import TopDocument
from letter_writer.agentic_service import (
    get_agentic_state,
    run_agentic_draft,
    run_agentic_draft_multi,
    run_agentic_feedback_round,
    run_agentic_refine,
    run_agentic_voting,
    slim_agentic_state_for_response,
    start_agentic_feedback,
    add_agentic_round,
    add_agentic_round_to_state,
    poll_response,
    normalize_agentic_feedback_if_rounds_exhausted,
    warn_agentic_round_limit_issues,
    _get_topic_cursors,
    _empty_threads,
    clear_phase_progress,
    PHASE_A1,
    PHASE_A3,
    PHASE_B,
    PHASES_SUBCOMMENT_ADD,
    PHASES_SUBCOMMENT_VOTE,
    call_agentic_phase_action,
    apply_phase_a1_comment,
    apply_phase_subcomments,
    apply_phase_subcomment_votes,
    prune_downvoted_subcomments,
    apply_phase_addendums,
    format_global_threads_for_voting,
    format_topic_thread_for_voting,
    apply_global_votes_and_prune,
    build_phase_b_schema,
    build_phase_b_schema_for_topic,
    agentic_topic_human_label,
    build_phase_subcomment_vote_schema,
    build_agentic_phase_a_labels,
    _get_sub_comment_rounds,
    DEFAULT_MAX_ROUNDS,
    STATUS_DRAFT,
    STATUS_FEEDBACK,
    STATUS_FEEDBACK_DONE,
)

router = APIRouter(dependencies=[Depends(require_auth)])

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
    feedback_override: Optional[Dict[str, Any]] = None
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None


class FeedbackRequestContextBody(BaseModel):
    """Re-run context extraction for one feedback item with the same materials as the original checker."""

    category: str
    item_id: str


class AgenticDraftRequest(BaseModel):
    """If draft_vendors is non-empty, one draft per vendor is generated (honors selection at top). Else single draft with draft_vendor."""
    draft_vendor: Optional[str] = None
    draft_vendors: Optional[List[str]] = None
    company_report: Optional[str] = None
    # JSON bodies stay Dict[str, Any] at the boundary; cast to TopDocument in handlers (see typed_shapes).
    top_docs: Optional[List[Dict[str, Any]]] = None
    style_instructions: Optional[str] = None
    max_rounds: Optional[int] = None
    sub_comment_rounds: Optional[int] = Field(
        default=None,
        ge=0,
        le=8,
        description="Sub-comment add+vote cycles after A1 per main round (default 0).",
    )


class AgenticRunRoundRequest(BaseModel):
    feedback_vendors: List[str]


class AgenticRefineRequest(BaseModel):
    """Optional edited threads to use for the rewrite (user may have edited/removed comments)."""
    threads: Optional[Dict[str, List[Dict[str, Any]]]] = None
    refine_sample_count: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="How many draft letters to sample as references when refining (default 2 from server/env).",
    )


class AgenticSuspendRequest(BaseModel):
    """Suspend feedback globally (all=True)."""
    all: Optional[bool] = None


class AgenticResumeRequest(BaseModel):
    """Resume feedback globally (all=True)."""
    all: Optional[bool] = None


class AgenticAddRoundRequest(BaseModel):
    """Add one round: all=True for all topics (increment max_rounds), or topic='instruction' etc. for one topic."""
    all: Optional[bool] = None
    topic: Optional[str] = None


class AgenticVoteRequest(BaseModel):
    """Voting vendors: each votes for their top 3 favorite drafts."""
    voting_vendors: List[str]

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

@router.get("/state/")
def get_session_state(session: Session = Depends(get_session)):
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
def clear_session(session: Session = Depends(get_session)):
    old_id = session.session_key
    user = session.get("user")
    # Stop any running agentic worker for this session before discarding it.
    if old_id:
        entry = _get_agentic_live(old_id)
        if entry:
            with entry["meta_lock"]:
                entry["state"]["feedback_ongoing"] = False
                entry["state"]["worker_running"] = False
            with _agentic_live_store_lock:
                _agentic_live_store.pop(old_id, None)
    session.clear()
    if user:
        session["user"] = user
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
    fields = ["company_name", "job_title", "location", "language", "salary", "requirements", "competences", "point_of_contact", "additional_user_info", "additional_company_info"]
    for field in fields:
        if field in data:
            common[field] = data[field]
            
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
    
    # Support overrides
    if data.company_report:
        vendor_state = VendorPhaseState(
            top_docs=cast(List[TopDocument], data.top_docs or []),
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
            top_docs_override=data.top_docs,
            style_instructions=instructions,
            user_id=user_id,
        )
        return with_user_monthly_cost({
            "status": "ok",
            "draft_letter": state.draft_letter,
            "feedback": state.feedback,
            "cost": state.cost
        }, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
            top_docs_override=data.top_docs,
            fancy=data.fancy,
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
        if cat == "instruction":
            system, base_prompt = _phased_feedback_checker_instruction_prompts(
                letter=draft,
                style_instructions=session.get("style_instructions") or "",
            )
            new_items = _run_suggest_additional_feedback_context(
                ai_client,
                cat,
                obs,
                ctx_items,
                system,
                base_prompt,
                top_docs=None,
            )
        elif cat == "accuracy":
            metadata = session.get("metadata") or {}
            uid = (user or {}).get("id") if user else None
            system, base_prompt = _phased_feedback_checker_accuracy_prompts(
                letter=draft,
                cv_text=session.get("cv_text") or "",
                additional_user_info=get_effective_additional_user_info(metadata, vendor_enum, uid),
            )
            new_items = _run_suggest_additional_feedback_context(
                ai_client,
                cat,
                obs,
                ctx_items,
                system,
                base_prompt,
                top_docs=None,
            )
        elif cat == "precision":
            system, base_prompt = _phased_feedback_checker_precision_prompts(
                letter=draft,
                company_report=vstate.company_report or "",
                job_text=session.get("job_text") or "",
            )
            new_items = _run_suggest_additional_feedback_context(
                ai_client,
                cat,
                obs,
                ctx_items,
                system,
                base_prompt,
                top_docs=None,
            )
        elif cat == "company_fit":
            system, base_prompt = _phased_feedback_checker_company_fit_prompts(
                letter=draft,
                company_report=vstate.company_report or "",
                job_text=session.get("job_text") or "",
            )
            new_items = _run_suggest_additional_feedback_context(
                ai_client,
                cat,
                obs,
                ctx_items,
                system,
                base_prompt,
                top_docs=None,
            )
        elif cat == "user_fit":
            metadata = session.get("metadata") or {}
            uid = (user or {}).get("id") if user else None
            top_docs = vstate.top_docs or []
            system, base_prompt = _phased_feedback_checker_user_fit_prompts(
                letter=draft,
                cv_text=session.get("cv_text") or "",
                additional_user_info=get_effective_additional_user_info(metadata, vendor_enum, uid),
                top_docs=top_docs,
            )
            new_items = _run_suggest_additional_feedback_context(
                ai_client,
                cat,
                obs,
                ctx_items,
                system,
                base_prompt,
                top_docs=top_docs,
            )
        elif cat == "human":
            top_docs = vstate.top_docs or []
            human_prompts = _phased_feedback_checker_human_prompts(letter=draft, top_docs=top_docs)
            if human_prompts is None:
                raise ValueError(
                    "The human-dimension checker has no reference materials (no AI letter examples with revision history)."
                )
            system, base_prompt = human_prompts
            new_items = _run_suggest_additional_feedback_context(
                ai_client,
                cat,
                obs,
                ctx_items,
                system,
                base_prompt,
                top_docs=top_docs,
            )
        else:
            raise AssertionError(f"Unhandled phased feedback category: {cat!r}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    user_id = (user or {}).get("id") or "anonymous"
    _update_cost(vstate, ai_client, phase="feedback", user_id=user_id, vendor_str=vendor_enum.value)
    save_vendor_data(session_key, vendor, vstate)

    return with_user_monthly_cost(
        {"status": "ok", "items": new_items, "cost": vstate.cost},
        session,
    )


# --- Agentic (per-topic) flow ---

@router.post("/agentic/draft/")
def agentic_draft(data: AgenticDraftRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.agentic_draft", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not session.get("job_text"):
        raise HTTPException(status_code=400, detail="Job text is missing")
    draft_vendors = [v for v in (data.draft_vendors or []) if v]
    if draft_vendors:
        try:
            state = run_agentic_draft_multi(
                session,
                draft_vendors=draft_vendors,
                company_report_override=data.company_report,
                top_docs_override=cast(Optional[List[TopDocument]], data.top_docs),
                style_instructions=data.style_instructions or "",
                max_rounds=data.max_rounds,
                sub_comment_rounds=data.sub_comment_rounds,
            )
            return with_user_monthly_cost({"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}, session)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    draft_vendor = data.draft_vendor
    if not draft_vendor:
        user_data = get_user_data(user["id"], use_cache=True) or {}
        agentic_draft = get_agentic_draft_model(user_data)
        default_models = get_models(user_data)
        if agentic_draft:
            draft_vendor = agentic_draft
        elif isinstance(default_models, list) and len(default_models) > 0:
            draft_vendor = default_models[0]
        else:
            draft_vendor = "openai"
    try:
        state = run_agentic_draft(
            session,
            draft_vendor=draft_vendor,
            company_report_override=data.company_report,
            top_docs_override=cast(Optional[List[TopDocument]], data.top_docs),
            style_instructions=data.style_instructions or "",
            max_rounds=data.max_rounds,
            sub_comment_rounds=data.sub_comment_rounds,
        )
        return with_user_monthly_cost({"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agentic/state/")
def agentic_state(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_key = session.session_key
    state = get_agentic_state(session)
    # Prefer live store (has threads) over session (which never has threads).
    entry = _get_agentic_live(session_key) if session_key else None
    if entry:
        with entry["meta_lock"]:
            live_state = dict(entry["state"])
        # Merge: use live state as base (has threads) with session fields for anything missing.
        merged = {**(state or {}), **{k: v for k, v in live_state.items() if v is not None}}
        state = merged
    elif session_key:
        # No live entry — try disk so threads are included in the restore response.
        try:
            persisted = load_session_from_storage(session_key)
            disk_state = (persisted or {}).get("agentic") if persisted else None
            if disk_state and any(
                (disk_state.get("threads") or {}).get(t) for t in AGENTIC_TOPIC_KEYS
            ):
                state = disk_state
        except Exception as e:
            logger.warning("agentic state disk load fallback failed: %s", e)
    return with_user_monthly_cost({"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}, session)


@router.post("/agentic/feedback/start/")
def agentic_feedback_start(data: AgenticRunRoundRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.agentic_feedback_start", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.feedback_vendors:
        raise HTTPException(status_code=400, detail="feedback_vendors is required")
    try:
        start_agentic_feedback(session, feedback_vendors=data.feedback_vendors)
        state = get_agentic_state(session)
        session_key = session.session_key
        if session_key and state and state.get("feedback_ongoing"):
            # Establish a single heartbeat timestamp before worker launch so startup cannot race
            # against stale/zero heartbeat reads.
            start_poll_at = time.time()
            persist_agentic_last_poll_at(session_key, start_poll_at)
            entry = _get_agentic_live(session_key)
            if entry is None:
                entry = _create_agentic_live(session_key, state)
            else:
                # A previous feedback run may have left an in-memory entry with
                # feedback_ongoing=False. Only updating last_poll_at would leave the worker
                # thinking feedback is off, so it exits immediately and no comments appear.
                # We update the state in-place so any running worker sees the fresh state.
                with entry["meta_lock"]:
                    was_running = entry["state"].get("worker_running", False)
                    # Preserve threads from the live state: session["agentic"] is written
                    # before threads are built, so the session state used here may not have
                    # them.  Threads from the live entry are the authoritative copy.
                    live_threads = entry["state"].get("threads")
                    entry["state"].clear()
                    entry["state"].update(copy.deepcopy(state))
                    entry["state"]["worker_running"] = was_running
                    if live_threads and not any(
                        entry["state"].get("threads", {}).get(t) for t in AGENTIC_TOPIC_KEYS
                    ):
                        entry["state"]["threads"] = live_threads
            with entry["meta_lock"]:
                entry["state"]["last_poll_at"] = start_poll_at
                if not entry["state"].get("worker_running"):
                    entry["state"]["worker_running"] = True
                    _launch_feedback_worker(session_key, entry)
        return with_user_monthly_cost(poll_response(state), session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("AGENTIC feedback/start failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


logger = logging.getLogger(__name__)

# Thread pool for background feedback workers.
_feedback_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentic_feedback")

# In-memory live state for feedback: same process, same RAM.
_agentic_live_store: Dict[str, Dict[str, Any]] = {}
_agentic_live_store_lock = Lock()


def _launch_feedback_worker(session_key: str, entry: Dict[str, Any]) -> None:
    """Launch the background worker and ensure worker_running is reset on crash.

    Uses ThreadPoolExecutor.submit (not asyncio) so this is safe when called from
    Starlette's sync-route thread pool as well as from the main event-loop thread.
    """
    future = _feedback_executor.submit(_run_ordered_feedback_loop, session_key)

    def _on_done(fut: Any, sk: str = session_key) -> None:
        try:
            fut.result()
        except Exception:
            logger.exception("AGENTIC ordered worker failed for session %s", sk)
            # Reset worker_running on crash so it can be restarted
            curr_entry = _get_agentic_live(sk)
            if curr_entry:
                with curr_entry["meta_lock"]:
                    curr_entry["state"]["worker_running"] = False
                    _persist_agentic_from_live(sk, curr_entry["state"])

    future.add_done_callback(_on_done)


def _get_agentic_live(session_key: str) -> Optional[Dict[str, Any]]:
    """Return the live agentic entry for this session if any."""
    with _agentic_live_store_lock:
        return _agentic_live_store.get(session_key)


def _create_agentic_live(session_key: str, initial_agentic_state: Dict[str, Any]) -> Dict[str, Any]:
    """Register in-memory state for ordered feedback loop. Returns the entry."""
    state = copy.deepcopy(initial_agentic_state)
    state.setdefault("threads", _empty_threads())
    state.setdefault("topic_cursors", {})
    state["worker_running"] = False
    _get_topic_cursors(state)
    entry = {
        "state": state,
        "meta_lock": Lock(),
    }
    with _agentic_live_store_lock:
        _agentic_live_store[session_key] = entry
    return entry


def _init_phase_a_progress(
    state: Dict[str, Any],
    topic: str,
    phase_label: str,
    round_num: int,
    feedback_vendors: List[str],
) -> None:
    """Initialise all vendor tasks for one topic's Phase-A sub-phase as pending (False).

    Called once per topic per sub-phase, before API calls are submitted, so
    waiting_for is never null during the window before the first result arrives.
    Each worker thread then independently flips its own flag to True when done.
    """
    prog = state.setdefault("phase_progress", {})
    prog["phase"] = phase_label
    prog["round"] = round_num
    tasks = prog.setdefault("tasks", {})
    for vendor in feedback_vendors:
        tasks.setdefault(f"{topic}::{vendor}", False)


def _mark_phase_a_done(state: Dict[str, Any], topic: str, vendor: str) -> None:
    """Mark one Phase-A (topic, vendor) task as complete."""
    tasks = (state.get("phase_progress") or {}).get("tasks")
    if tasks is not None:
        tasks[f"{topic}::{vendor}"] = True


def _init_phase_b_progress(
    state: Dict[str, Any],
    round_num: int,
    vote_tuples: List[Tuple[str, str, str]],
) -> None:
    """Initialise all (src, target, vendor) tasks for Phase B as pending."""
    tasks = {f"{src}::{tgt}::{vendor}": False for vendor, src, tgt in vote_tuples}
    state["phase_progress"] = {
        "phase": "Cross-topic vote",
        "round": round_num,
        "tasks": tasks,
    }


def _mark_phase_b_done(
    state: Dict[str, Any], vendor: str, source_topic: str, target_topic: str
) -> None:
    """Mark one Phase-B (src, target, vendor) task as complete."""
    tasks = (state.get("phase_progress") or {}).get("tasks")
    if tasks is not None:
        tasks[f"{source_topic}::{target_topic}::{vendor}"] = True


def _run_ordered_feedback_loop(session_key: str) -> None:
    """Run feedback in global rounds: A1 → (optional sub-comment cycles)×N → A3 → B."""
    entry = _get_agentic_live(session_key)
    if not entry:
        return
    state = entry["state"]
    meta_lock = entry["meta_lock"]
    Path("trace", "agentic.feedback").mkdir(parents=True, exist_ok=True)

    def _stop_feedback_worker() -> None:
        with meta_lock:
            state["feedback_ongoing"] = False
            state["feedback_suspended"] = False
            if state.get("status") not in (STATUS_DRAFT, STATUS_FEEDBACK_DONE):
                state["status"] = STATUS_FEEDBACK
            state["worker_running"] = False
            clear_phase_progress(state)
            _persist_agentic_from_live(session_key, state)

    while True:
        with meta_lock:
            if not state.get("feedback_ongoing"):
                state["worker_running"] = False
                clear_phase_progress(state)
                _persist_agentic_from_live(session_key, state)
                return
            last_poll_at_mem = float(state.get("last_poll_at") or 0.0)
            try:
                last_poll_at_disk = float(
                    get_agentic_last_poll_at_from_storage(session_key) or 0.0
                )
            except Exception:
                last_poll_at_disk = 0.0
            last_poll_at = max(last_poll_at_mem, last_poll_at_disk)
            state["last_poll_at"] = last_poll_at
            if bool(state.get("feedback_suspended")):
                state["feedback_ongoing"] = False
                state["worker_running"] = False
                clear_phase_progress(state)
                _persist_agentic_from_live(session_key, state)
                return
            threads = state.get("threads") or _empty_threads()
            state["threads"] = threads
            topic_cursors = state.get("topic_cursors") or {}
            state["topic_cursors"] = topic_cursors
            max_rounds = int(state.get("max_rounds", DEFAULT_MAX_ROUNDS))
            sub_comment_rounds_cfg = _get_sub_comment_rounds(state)
            draft_letter = state.get("draft_letter") or ""
            draft_vendor = state.get("draft_vendor") or ""
            top_docs = state.get("top_docs") or []
            company_report = state.get("company_report") or ""
            job_text = state.get("job_text") or ""
            cv_text = state.get("cv_text") or ""
            metadata = state.get("metadata") or {}
            style_instructions = state.get("style_instructions") or get_style_instructions()
            draft_letters_multi = state.get("draft_letters") or {}
            rounds = {t: int((topic_cursors.get(t) or {}).get("round", 1)) for t in AGENTIC_TOPIC_KEYS}
            active_topics = [t for t in AGENTIC_TOPIC_KEYS if rounds.get(t, 1) <= max_rounds]
            feedback_vendors = cast(
                List[str], list(state.get("feedback_vendor_order") or [])
            )

        if not active_topics:
            with meta_lock:
                state["feedback_ongoing"] = False
                state["status"] = STATUS_FEEDBACK_DONE
                state["worker_running"] = False
                clear_phase_progress(state)
                state["threads"] = threads
                state["topic_cursors"] = topic_cursors
                _persist_agentic_from_live(session_key, state)
            return
        if not feedback_vendors:
            _stop_feedback_worker()
            return

        persisted = load_session_from_storage(session_key)
        uid = (persisted.get("user") or {}).get("id") if isinstance(persisted, dict) else None
        additional_user_info = get_effective_additional_user_info(
            metadata, ModelVendor(draft_vendor), uid
        )
        topic_contexts = {
            t: get_agentic_topic_context(
                t,
                draft_letter,
                cv_text,
                company_report,
                job_text,
                top_docs,
                style_instructions,
                additional_user_info,
                draft_letters=draft_letters_multi if len(draft_letters_multi) > 0 else None,
            )
            for t in active_topics
        }
        round_num = min(rounds.get(t, 1) for t in active_topics)

        phase_labels = build_agentic_phase_a_labels(sub_comment_rounds_cfg)
        # --- Phase A: each topic pipelines through A1→A3 independently ---
        # Topics run concurrently; within each topic, sub-phases are sequential
        # (A1 results feed into A2a1, etc.).  The only sync barrier is after all
        # topics complete Phase A, before entering Phase B (global voting).
        #
        # Phase-resume: each topic cursor stores ``last_completed_phase_idx``
        # so that if the worker is restarted mid-round (e.g. stale-poll abort
        # + auto-resume) we skip already-completed sub-phases instead of
        # re-running them, which would appear as the status going backwards.

        # Per-topic progress tracking (topic → current phase label).
        topic_phase_status: Dict[str, str] = {t: phase_labels[0][1] for t in active_topics}

        def _run_topic_pipeline(topic: str) -> None:
            """Run one topic through all Phase-A sub-phases sequentially."""
            with meta_lock:
                cur = topic_cursors.get(topic) or {}
                resume_from = int(cur.get("last_completed_phase_idx", -1)) + 1
            for phase_idx, (phase_key, phase_label) in enumerate(phase_labels):
                if phase_idx < resume_from:
                    continue  # already completed in a previous worker run
                with meta_lock:
                    topic_phase_status[topic] = phase_label
                    thread_snapshot = copy.deepcopy(threads.get(topic) or [])

                # Run all vendors in parallel for this topic + phase.
                vendor_results: List[Tuple[str, Dict[str, Any]]] = []
                done_vendors: Set[str] = set()
                # Initialise all tasks as pending before submitting so
                # waiting_for is never null while API calls are in flight.
                with meta_lock:
                    _init_phase_a_progress(
                        state, topic, phase_label, round_num, feedback_vendors
                    )
                with ThreadPoolExecutor(max_workers=max(1, len(feedback_vendors))) as executor:
                    vendor_futures = {}
                    for vendor in feedback_vendors:
                        schema_ov = (
                            build_phase_subcomment_vote_schema(thread_snapshot)
                            if phase_key in PHASES_SUBCOMMENT_VOTE
                            else None
                        )
                        fut = executor.submit(
                            cast(Callable[..., None], call_agentic_phase_action),
                            vendor=vendor,
                            phase=phase_key,
                            topic=topic,
                            context=topic_contexts[topic],
                            thread=thread_snapshot,
                            schema_override=schema_ov,
                        )
                        vendor_futures[fut] = vendor
                    for fut in as_completed(vendor_futures):
                        vendor = vendor_futures[fut]
                        try:
                            payload: Dict[str, Any] = fut.result() or {}
                        except Exception as e:
                            logger.exception(
                                "AGENTIC phase error phase=%s topic=%s vendor=%s err=%s",
                                phase_key, topic, vendor, e,
                            )
                            payload = {}
                            with meta_lock:
                                state.setdefault("vendor_errors", {})[vendor] = (
                                    f"Error in {phase_key} ({topic}): {e}"
                                )
                        vendor_results.append((vendor, payload))
                        done_vendors.add(vendor)
                        with meta_lock:
                            _mark_phase_a_done(state, topic, vendor)

                # Apply results to the live thread under lock.
                with meta_lock:
                    thread = threads.get(topic) or []
                    for vendor, payload in vendor_results:
                        if phase_key == PHASE_A1:
                            apply_phase_a1_comment(thread, vendor, payload.get("new_comment"), round_num=round_num)
                        elif phase_key in PHASES_SUBCOMMENT_ADD:
                            apply_phase_subcomments(thread, vendor, payload.get("subcomments") or [])
                        elif phase_key in PHASES_SUBCOMMENT_VOTE:
                            apply_phase_subcomment_votes(
                                thread, vendor, payload.get("subcomment_votes") or []
                            )
                        elif phase_key == PHASE_A3:
                            apply_phase_addendums(thread, vendor, payload.get("addendums") or [])
                    threads[topic] = thread
                    if phase_key in PHASES_SUBCOMMENT_VOTE:
                        prune_downvoted_subcomments(threads.get(topic) or [])
                    # Record completed phase so a restarted worker resumes
                    # from the next sub-phase instead of replaying from A1.
                    cur = topic_cursors.setdefault(topic, {})
                    cur["last_completed_phase_idx"] = phase_idx
                    state["topic_cursors"] = topic_cursors
                    state["threads"] = threads
                    # Only persist this topic's slice — other topics' disk data
                    # is untouched, so concurrent workers can't clobber each other.
                    save_agentic_topic_slice_to_storage(
                        session_key, topic, threads.get(topic), cur
                    )

        # Launch all topic pipelines concurrently; wait for all to finish.
        with ThreadPoolExecutor(max_workers=max(1, len(active_topics))) as topic_executor:
            topic_futures = {
                topic_executor.submit(_run_topic_pipeline, t): t
                for t in active_topics
            }
            for fut in as_completed(topic_futures):
                t = topic_futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    logger.exception("AGENTIC topic pipeline error topic=%s err=%s", t, e)

        # --- Phase B: per-tuple cross-topic voting ---
        # For every (vendor, source_topic, target_topic) tuple, the vendor
        # acts in the context of source_topic and votes on comments from
        # target_topic.  All tuples run fully in parallel.

        # Pre-build per-topic thread strings and schemas under lock.
        with meta_lock:
            per_topic_threads_str: Dict[str, str] = {}
            per_topic_schema: Dict[str, Dict[str, Any]] = {}
            for t in active_topics:
                t_thread = threads.get(t) or []
                per_topic_threads_str[t] = format_topic_thread_for_voting(t_thread, t)
                per_topic_schema[t] = build_phase_b_schema_for_topic(t_thread, t)

        # Build all (vendor, source_topic, target_topic) tuples — including
        # same-topic pairs so each topic also evaluates its own comments.
        vote_tuples: List[Tuple[str, str, str]] = []
        for vendor in feedback_vendors:
            for source_topic in active_topics:
                for target_topic in active_topics:
                    vote_tuples.append((vendor, source_topic, target_topic))

        with meta_lock:
            _init_phase_b_progress(state, round_num, vote_tuples)

        vote_results: List[Tuple[str, str, Dict[str, Any]]] = []
        done_count = 0
        with ThreadPoolExecutor(max_workers=min(len(vote_tuples), 24)) as executor:
            vote_futures: Dict[Any, Tuple[str, str, str]] = {}
            for vendor, source_topic, target_topic in vote_tuples:
                source_label = agentic_topic_human_label(source_topic)
                target_label = agentic_topic_human_label(target_topic)
                tuple_context = (
                    f"You are reviewing from the perspective of '{source_label}'.\n"
                    f"Vote on the '{target_label}' comments below.\n\n"
                    f"Job:\n{job_text}\n\n"
                    f"Draft vendor: {draft_vendor}\n\n"
                    f"Draft letter:\n{draft_letter}\n\n"
                    f"Company report:\n{company_report}\n"
                )
                fut = executor.submit(
                    cast(Callable[..., None], call_agentic_phase_action),
                    vendor=vendor,
                    phase=PHASE_B,
                    topic=target_topic,
                    context=tuple_context,
                    global_threads_str=per_topic_threads_str[target_topic],
                    schema_override=per_topic_schema[target_topic],
                )
                vote_futures[fut] = (vendor, source_topic, target_topic)
            for fut in as_completed(vote_futures):
                vendor, source_topic, target_topic = vote_futures[fut]
                try:
                    payload: Dict[str, Any] = fut.result() or {}
                except Exception as e:
                    logger.exception(
                        "AGENTIC phase B error vendor=%s source=%s target=%s err=%s",
                        vendor, source_topic, target_topic, e,
                    )
                    payload = {}
                    with meta_lock:
                        state.setdefault("vendor_errors", {})[vendor] = (
                            f"Error in cross-topic voting ({source_topic}→{target_topic}): {e}"
                        )
                vote_results.append((vendor, source_topic, payload))
                done_count += 1
                with meta_lock:
                    _mark_phase_b_done(state, vendor, source_topic, target_topic)

        with meta_lock:
            apply_global_votes_and_prune(threads, vote_results, round_num=round_num)
            for topic in active_topics:
                cur = dict(topic_cursors.get(topic) or {"round": 1, "vendor_index": 0, "vendor_order": []})
                cur["round"] = int(cur.get("round", 1)) + 1
                cur["vendor_index"] = 0
                cur.pop("last_completed_phase_idx", None)  # reset for next round
                order = list(cur.get("vendor_order") or feedback_vendors)
                if order:
                    random.shuffle(order)
                    cur["vendor_order"] = order
                topic_cursors[topic] = cur
            state["threads"] = threads
            state["topic_cursors"] = topic_cursors
            _persist_agentic_from_live(session_key, state)


def _persist_agentic_from_live(session_key: str, state: Dict[str, Any]) -> None:
    """Write live agentic state back to session on disk.

    Uses save_agentic_state_to_storage which holds the exclusive file lock for
    the entire read-modify-write cycle, preventing concurrent topic workers from
    clobbering each other's thread updates.
    """
    try:
        save_agentic_state_to_storage(session_key, state)
    except Exception as e:
        logger.exception("AGENTIC persist from live failed: %s", e)


def _has_pending_feedback(state: Dict[str, Any]) -> bool:
    max_rounds = int(state.get("max_rounds", DEFAULT_MAX_ROUNDS))
    cursors = state.get("topic_cursors") or {}
    for topic in AGENTIC_TOPIC_KEYS:
        cur = (cursors.get(topic) or {})
        try:
            round_num = int(cur.get("round", 1) or 1)
        except Exception:
            round_num = 1
        if round_num <= max_rounds:
            return True
    return False


def _start_ordered_worker(session_key: str) -> None:
    future = _feedback_executor.submit(_run_ordered_feedback_loop, session_key)

    def _on_done(fut: Any, sk: str = session_key) -> None:
        try:
            fut.result()
        except Exception:
            logger.exception("AGENTIC ordered worker failed for session %s", sk)

    future.add_done_callback(_on_done)


@router.get("/agentic/feedback/poll/")
def agentic_feedback_poll(
    session: Session = Depends(get_session),
):
    logger.info("AGENTIC poll request")
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_key = session.session_key
    if not session_key:
        return with_user_monthly_cost(poll_response(None), session)
    now = time.time()
    entry = _get_agentic_live(session_key)
    if entry:
        live_state = entry["state"]
        with entry["meta_lock"]:
            live_state["last_poll_at"] = now
            should_auto_resume = (
                live_state.get("status") == STATUS_FEEDBACK
                and not bool(live_state.get("feedback_suspended"))
                and not bool(live_state.get("feedback_ongoing"))
                and not bool(live_state.get("worker_running"))
                and _has_pending_feedback(live_state)
            )
            if should_auto_resume:
                live_state["feedback_ongoing"] = True
                live_state["worker_running"] = True
                _persist_agentic_from_live(session_key, live_state)
                _start_ordered_worker(session_key)
            if live_state and normalize_agentic_feedback_if_rounds_exhausted(live_state):
                _persist_agentic_from_live(session_key, live_state)
            warn_agentic_round_limit_issues(live_state)
            snapshot: Dict[str, Any] = {
                "threads": copy.deepcopy(live_state.get("threads") or _empty_threads()),
                "topic_cursors": copy.deepcopy(live_state.get("topic_cursors") or {}),
                "last_poll_at": now,
            }
            for k in (
                "feedback_ongoing",
                "status",
                "round",
                "draft_letter",
                "final_letter",
                "cost",
                "draft_vendor",
                "feedback_suspended",
                "draft_letters",
                "final_letters",
                "max_rounds",
                "sub_comment_rounds",
                "draft_votes",
                # Required for poll_response / _build_topic_meta waiting_for (per-topic progress)
                "worker_running",
                "phase_progress",
            ):
                if k in live_state:
                    snapshot[k] = live_state[k]
        persist_agentic_last_poll_at(session_key, now)
        # If the live state has no thread content, fall back to persisted threads so
        # the client never receives a blank response while a valid history exists on disk.
        snap_threads = snapshot.get("threads") or {}
        if not any(bool(snap_threads.get(t)) for t in AGENTIC_TOPIC_KEYS):
            logger.warning(
                "AGENTIC poll live-state threads empty session=%s ongoing=%s status=%s — trying disk fallback",
                session_key,
                snapshot.get("feedback_ongoing"),
                snapshot.get("status"),
            )
            try:
                disk_session = load_session_from_storage(session_key)
                persisted_threads = (disk_session or {}).get("agentic", {}).get("threads") or {}
                if any(bool(persisted_threads.get(t)) for t in AGENTIC_TOPIC_KEYS):
                    snapshot["threads"] = persisted_threads
                    with entry["meta_lock"]:
                        live_state["threads"] = copy.deepcopy(persisted_threads)
                else:
                    logger.warning(
                        "AGENTIC poll disk fallback also empty session=%s",
                        session_key,
                    )
            except Exception as e:
                logger.warning("AGENTIC poll disk load fallback failed: %s", e)
        tc_raw = snapshot.get("topic_cursors")
        tc = tc_raw if isinstance(tc_raw, dict) else {}
        rounds_live = {}
        for t in AGENTIC_TOPIC_KEYS:
            cur_tc = tc.get(t)
            cur_dict = cur_tc if isinstance(cur_tc, dict) else {}
            rounds_live[t] = int(cur_dict.get("round", 1))
        prog_raw = snapshot.get("phase_progress")
        prog: Dict[str, Any] = prog_raw if isinstance(prog_raw, dict) else {}
        tasks_raw = prog.get("tasks")
        tasks: Dict[str, Any] = tasks_raw if isinstance(tasks_raw, dict) else {}
        pending_count = sum(1 for v in tasks.values() if v is not True)
        total_count = len(tasks)
        logger.info(
            "AGENTIC poll source=live session=%s ongoing=%s status=%s rounds=%s phase=%s pending=%d/%d",
            session_key,
            snapshot.get("feedback_ongoing"),
            snapshot.get("status"),
            rounds_live,
            prog.get("phase") or "—",
            pending_count,
            total_count,
        )
        return with_user_monthly_cost(
            poll_response(snapshot),
            session,
        )
    if "agentic" not in session:
        session["agentic"] = {}
    persist_agentic_last_poll_at(session_key, now)
    poll_agentic: Optional[Dict[str, Any]]
    try:
        persisted = load_session_from_storage(session_key) if session_key else None
        poll_agentic = (persisted or {}).get("agentic") or get_agentic_state(session)
        should_auto_resume = (
            poll_agentic
            and poll_agentic.get("status") == STATUS_FEEDBACK
            and not bool(poll_agentic.get("feedback_suspended"))
            and not bool(poll_agentic.get("feedback_ongoing"))
            and _has_pending_feedback(poll_agentic)
        )
        if should_auto_resume and try_acquire_agentic_lock(session_key, timeout_seconds=15.0):
            try:
                latest_payload = load_session_from_storage(session_key) if session_key else {}
                latest = (latest_payload or {}).get("agentic") or {}
                if latest:
                    poll_agentic = latest
                if (
                    poll_agentic
                    and poll_agentic.get("status") == STATUS_FEEDBACK
                    and not bool(poll_agentic.get("feedback_suspended"))
                    and not bool(poll_agentic.get("feedback_ongoing"))
                    and _has_pending_feedback(poll_agentic)
                ):
                    poll_agentic = dict(poll_agentic)
                    poll_agentic["feedback_ongoing"] = True
                    poll_agentic["worker_running"] = True
                    payload = latest_payload or {}
                    payload["agentic"] = poll_agentic
                    save_session_to_storage(session_key, payload)
                    with _agentic_live_store_lock:
                        if _agentic_live_store.get(session_key) is None:
                            _agentic_live_store[session_key] = {
                                "state": poll_agentic,
                                "meta_lock": Lock(),
                                "worker_running": True,
                            }
                            _start_ordered_worker(session_key)
            finally:
                release_agentic_lock(session_key)
        rounds_persisted = {
            t: int(
                (((poll_agentic or {}).get("topic_cursors") or {}).get(t) or {}).get("round", 1)
            )
            for t in AGENTIC_TOPIC_KEYS
        }
        prog_p = (poll_agentic or {}).get("phase_progress") or {}
        tasks_p = prog_p.get("tasks") or {}
        logger.info(
            "AGENTIC poll source=persisted session=%s ongoing=%s status=%s rounds=%s phase=%s pending=%d/%d",
            session_key,
            (poll_agentic or {}).get("feedback_ongoing"),
            (poll_agentic or {}).get("status"),
            rounds_persisted,
            prog_p.get("phase") or "—",
            sum(1 for v in tasks_p.values() if not v),
            len(tasks_p),
        )
    except Exception:
        poll_agentic = get_agentic_state(session)
        rounds_session = {
            t: int(
                (((poll_agentic or {}).get("topic_cursors") or {}).get(t) or {}).get("round", 1)
            )
            for t in AGENTIC_TOPIC_KEYS
        }
        logger.info(
            "AGENTIC poll source=session-fallback session=%s ongoing=%s status=%s rounds=%s",
            session_key,
            (poll_agentic or {}).get("feedback_ongoing"),
            (poll_agentic or {}).get("status"),
            rounds_session,
        )
    if poll_agentic and normalize_agentic_feedback_if_rounds_exhausted(poll_agentic):
        payload = load_session_from_storage(session_key) if session_key else {}
        if not isinstance(payload, dict):
            payload = {}
        payload["agentic"] = poll_agentic
        if session_key:
            save_session_to_storage(session_key, payload)
        session["agentic"] = poll_agentic
    warn_agentic_round_limit_issues(poll_agentic)

    # Ensure threads are preserved in the fallback response
    if poll_agentic and "threads" not in poll_agentic:
        poll_agentic["threads"] = _empty_threads()

    return with_user_monthly_cost(
        poll_response(poll_agentic),
        session,
    )


@router.post("/agentic/run-round/")
def agentic_run_round(data: AgenticRunRoundRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.agentic_run_round", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.feedback_vendors:
        raise HTTPException(status_code=400, detail="feedback_vendors is required")
    try:
        state = run_agentic_feedback_round(session, feedback_vendors=data.feedback_vendors)
        return with_user_monthly_cost({"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _apply_suspend(state: Dict[str, Any]) -> None:
    """Apply global suspend to state (live or session)."""
    state["feedback_suspended"] = True
    state["feedback_ongoing"] = False


def _apply_resume(state: Dict[str, Any]) -> bool:
    """Clear global suspend; set feedback_ongoing=True. Return whether ordered worker should run."""
    state["feedback_suspended"] = False
    state["feedback_ongoing"] = True
    max_rounds = state.get("max_rounds", DEFAULT_MAX_ROUNDS)
    cursors = state.get("topic_cursors") or {}
    for t in AGENTIC_TOPIC_KEYS:
        cur = (cursors or {}).get(t) or {}
        if (cur.get("round", 1) or 1) <= max_rounds:
            return True
    return False


@router.post("/agentic/feedback/suspend/")
def agentic_feedback_suspend(
    data: AgenticSuspendRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    set_current_request(request)
    log_user_input_event("phases.agentic_feedback_suspend", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    all_topics = data.all is True
    if not all_topics:
        raise HTTPException(status_code=400, detail="Provide all=true")
    session_key = session.session_key
    try:
        entry = _get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                _apply_suspend(state)
            return with_user_monthly_cost(poll_response(state), session)
        if not session_key:
            raise HTTPException(status_code=400, detail="No session")
        data_load = load_session_from_storage(session_key)
        state = copy.deepcopy((data_load.get("agentic") or {}))
        if not state or state.get("status") != "feedback":
            raise HTTPException(status_code=400, detail="No agentic feedback in progress")
        _apply_suspend(state)
        data_load["agentic"] = state
        save_session_to_storage(session_key, data_load)
        return with_user_monthly_cost(poll_response(state), session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/feedback/resume/")
def agentic_feedback_resume(
    data: AgenticResumeRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    set_current_request(request)
    log_user_input_event("phases.agentic_feedback_resume", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    all_topics = data.all is True
    if not all_topics:
        raise HTTPException(status_code=400, detail="Provide all=true")
    session_key = session.session_key
    if not session_key:
        raise HTTPException(status_code=400, detail="No session")
    try:
        entry = _get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                should_run = _apply_resume(state)
                can_start = should_run and not state.get("worker_running")
                if can_start:
                    state["worker_running"] = True
            if can_start:
                _launch_feedback_worker(session_key, entry)
            return with_user_monthly_cost(poll_response(state), session)
        data_load = load_session_from_storage(session_key) if session_key else None
        if not data_load or "agentic" not in data_load:
            raise HTTPException(status_code=400, detail="No agentic state to resume")
        state = copy.deepcopy(data_load["agentic"])
        state.setdefault("threads", _empty_threads())
        state.setdefault("topic_cursors", {})
        _get_topic_cursors(state)
        should_run = _apply_resume(state)
        if not should_run:
            if session_key:
                data_load["agentic"] = state
                save_session_to_storage(session_key, data_load)
            return with_user_monthly_cost(poll_response(state), session)
        with _agentic_live_store_lock:
            if _agentic_live_store.get(session_key) is not None:
                raise HTTPException(status_code=409, detail="Feedback already running")
            state["worker_running"] = True
            entry = {
                "state": state,
                "meta_lock": Lock(),
            }
            _agentic_live_store[session_key] = entry
        persist_agentic_last_poll_at(session_key, time.time())
        _launch_feedback_worker(session_key, entry)
        return with_user_monthly_cost(poll_response(state), session)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("AGENTIC resume failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/rounds/add/")
def agentic_rounds_add(
    data: AgenticAddRoundRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    set_current_request(request)
    log_user_input_event("phases.agentic_rounds_add", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    all_topics = data.all is True
    topic = data.topic if (data.topic and not all_topics) else None
    if not all_topics and not topic:
        raise HTTPException(status_code=400, detail="Provide all=true or topic=<key>")
    if topic and topic not in AGENTIC_TOPIC_KEYS:
        raise HTTPException(status_code=400, detail=f"topic must be one of {AGENTIC_TOPIC_KEYS}")
    session_key = session.session_key
    if not session_key:
        raise HTTPException(status_code=400, detail="No session")
    try:
        entry = _get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                add_agentic_round_to_state(state, all_topics=all_topics, topic=topic)
            _persist_agentic_from_live(session_key, state)
            session["agentic"] = dict(state)
            return with_user_monthly_cost(poll_response(state), session)
        state = add_agentic_round(session, all_topics=all_topics, topic=topic)
        return with_user_monthly_cost(poll_response(state), session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("AGENTIC add round failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/vote/")
def agentic_vote(data: AgenticVoteRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    log_user_input_event("phases.agentic_vote", data.dict(exclude_none=True))
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.voting_vendors:
        raise HTTPException(status_code=400, detail="voting_vendors is required")
    try:
        state = run_agentic_voting(session, voting_vendors=data.voting_vendors)
        # Voting only produces incremental data for the client (status + votes + optional cost).
        response: Dict[str, Any] = {
            "status": "ok",
            "agentic_update": {
                "status": state.get("status"),
                "draft_votes": state.get("draft_votes"),
            },
        }
        if state.get("cost") is not None:
            response["agentic_update"]["cost"] = state.get("cost")
        return with_user_monthly_cost(response, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/refine/")
def agentic_refine(request: Request, session: Session = Depends(get_session), body: Optional[AgenticRefineRequest] = Body(None), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("phases.agentic_refine", body.dict(exclude_none=True) if body else {})
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        threads_override = body.threads if body and body.threads is not None else None
        refine_n = body.refine_sample_count if body and body.refine_sample_count is not None else None
        state = run_agentic_refine(session, threads_override=threads_override, refine_sample_count=refine_n)
        # Refine produces final output; send only fields the client does not already have.
        response: Dict[str, Any] = {
            "status": "ok",
            "agentic_update": {
                "status": state.get("status"),
                "final_letter": state.get("final_letter"),
                "final_letters": state.get("final_letters"),
                "refine_samples": state.get("refine_samples") or {},
            },
        }
        if state.get("cost") is not None:
            response["agentic_update"]["cost"] = state.get("cost")
        return with_user_monthly_cost(response, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
