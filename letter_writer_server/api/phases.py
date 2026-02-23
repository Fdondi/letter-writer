import asyncio
import copy
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import (
    Session,
    get_session,
    get_agentic_last_poll_at_from_storage,
    load_session_from_storage,
    save_session_to_storage,
    persist_agentic_last_poll_at,
)
from letter_writer.generation import AGENTIC_TOPIC_KEYS, get_agentic_topic_context, get_style_instructions
from letter_writer.phased_service import get_metadata_field
from letter_writer.clients.base import ModelVendor
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
from letter_writer.personal_data_sections import get_models, get_agentic_draft_model
from letter_writer.agentic_service import (
    get_agentic_state,
    run_agentic_draft,
    run_agentic_feedback_round,
    run_agentic_refine,
    slim_agentic_state_for_response,
    start_agentic_feedback,
    poll_response,
    _run_one_topic_agent,
    _get_topic_cursors,
    _empty_threads,
    MAX_ROUNDS,
    POLL_ABORT_SECONDS,
    STATUS_FEEDBACK_DONE,
)

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


class AgenticDraftRequest(BaseModel):
    draft_vendor: Optional[str] = None
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None
    style_instructions: Optional[str] = None


class AgenticRunRoundRequest(BaseModel):
    feedback_vendors: List[str]


class AgenticRefineRequest(BaseModel):
    """Optional edited threads to use for the rewrite (user may have edited/removed comments)."""
    threads: Optional[Dict[str, List[Dict[str, Any]]]] = None


class AgenticSuspendRequest(BaseModel):
    """Suspend all threads (all=True) or specific topics (topics=[...])."""
    all: Optional[bool] = None
    topics: Optional[List[str]] = None


class AgenticResumeRequest(BaseModel):
    """Resume all threads (all=True) or specific topics (topics=[...])."""
    all: Optional[bool] = None
    topics: Optional[List[str]] = None

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


# --- Agentic (per-topic) flow ---

@router.post("/agentic/draft/")
async def agentic_draft(data: AgenticDraftRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not session.get("job_text"):
        raise HTTPException(status_code=400, detail="Job text is missing")
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
            top_docs_override=data.top_docs,
            style_instructions=data.style_instructions or "",
        )
        return {"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agentic/state/")
async def agentic_state(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    state = get_agentic_state(session)
    return {"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}


@router.post("/agentic/feedback/start/")
async def agentic_feedback_start(data: AgenticRunRoundRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
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
            if _get_agentic_live(session_key) is None:
                _create_agentic_live(session_key, state)
                loop = asyncio.get_event_loop()
                for topic in AGENTIC_TOPIC_KEYS:
                    future = loop.run_in_executor(_feedback_executor, _run_topic_loop, session_key, topic)
                    def _on_done(f, sk=session_key, t=topic):
                        try:
                            f.result()
                        except Exception:
                            logger.exception("AGENTIC topic %s failed for session %s", t, sk)
                    future.add_done_callback(_on_done)
        return poll_response(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


logger = logging.getLogger(__name__)

# Thread pool for one thread per topic (no blocking between topics).
_feedback_executor = ThreadPoolExecutor(max_workers=max(8, len(AGENTIC_TOPIC_KEYS)), thread_name_prefix="agentic_feedback")

# In-memory live state for feedback: same process, same RAM; per-topic locks for each topic's slot.
_agentic_live_store: Dict[str, Dict[str, Any]] = {}
_agentic_live_store_lock = Lock()


def _get_agentic_live(session_key: str) -> Optional[Dict[str, Any]]:
    """Return the live agentic entry for this session if any."""
    with _agentic_live_store_lock:
        return _agentic_live_store.get(session_key)


def _create_agentic_live(session_key: str, initial_agentic_state: Dict[str, Any]) -> Dict[str, Any]:
    """Register in-memory state and per-topic locks for this session. Returns the entry."""
    state = copy.deepcopy(initial_agentic_state)
    state.setdefault("threads", _empty_threads())
    state.setdefault("topic_cursors", {})
    _get_topic_cursors(state)
    entry = {
        "state": state,
        "topic_locks": {t: Lock() for t in AGENTIC_TOPIC_KEYS},
        "meta_lock": Lock(),
        "running_count": len(AGENTIC_TOPIC_KEYS),
    }
    with _agentic_live_store_lock:
        _agentic_live_store[session_key] = entry
    return entry


def _run_topic_loop(session_key: str, topic: str) -> None:
    """Run this topic until it is done (round > MAX_ROUNDS), suspended, or abort (no poll for 30s). No topic checks others."""
    entry = _get_agentic_live(session_key)
    if not entry:
        return
    state = entry["state"]
    topic_lock = entry["topic_locks"][topic]
    meta_lock = entry["meta_lock"]
    trace_dir = Path("trace", "agentic.feedback")
    trace_dir.mkdir(parents=True, exist_ok=True)
    # Shared context (read-only)
    draft_letter = state.get("draft_letter") or ""
    draft_vendor = state.get("draft_vendor") or ""
    top_docs = state.get("top_docs") or []
    company_report = state.get("company_report") or ""
    job_text = state.get("job_text") or ""
    cv_text = state.get("cv_text") or ""
    metadata = state.get("metadata") or {}
    style_instructions = state.get("style_instructions") or get_style_instructions()
    additional_user_info = get_metadata_field(metadata, ModelVendor(draft_vendor), "additional_user_info", "")

    def _exit_persist_if_last(suspended_exit: bool) -> None:
        with meta_lock:
            entry["running_count"] -= 1
            if entry["running_count"] <= 0:
                state["feedback_ongoing"] = False
                if not suspended_exit:
                    state["status"] = STATUS_FEEDBACK_DONE
                _persist_agentic_from_live(session_key, state)

    while True:
        now = time.time()
        with meta_lock:
            last_poll_at = float(state.get("last_poll_at") or 0.0)
            feedback_suspended = bool(state.get("feedback_suspended"))
        if feedback_suspended:
            logger.info("AGENTIC topic %s exiting due to global suspend", topic)
            _exit_persist_if_last(suspended_exit=True)
            return
        if (now - last_poll_at) > POLL_ABORT_SECONDS:
            logger.info("AGENTIC feedback aborted: no poll from client for %.1fs (threshold %ds)", now - last_poll_at, POLL_ABORT_SECONDS)
            with meta_lock:
                state["feedback_ongoing"] = False
                state["status"] = STATUS_FEEDBACK_DONE
                entry["running_count"] -= 1
                if entry["running_count"] <= 0:
                    _persist_agentic_from_live(session_key, state)
            return

        with topic_lock:
            threads = state.get("threads") or _empty_threads()
            topic_cursors = state.get("topic_cursors") or {}
            cur = dict(topic_cursors.get(topic) or {"round": 1, "vendor_index": 0, "vendor_order": []})
            if cur.get("suspended"):
                logger.info("AGENTIC topic %s exiting due to per-topic suspend", topic)
                _exit_persist_if_last(suspended_exit=True)
                return
            order = list(cur.get("vendor_order") or [])
            vi = cur.get("vendor_index", 0)
            thread_copy = list(threads.get(topic, []))

        if vi >= len(order):
            with topic_lock:
                if "topic_cursors" not in state:
                    state["topic_cursors"] = {}
                cur = state["topic_cursors"].get(topic) or cur
                if order:
                    cur["vendor_index"] = 0
                    cur["round"] = cur.get("round", 1) + 1
                    random.shuffle(order)
                    state["topic_cursors"][topic] = cur
                r = cur.get("round", 1)
            if not order or r > MAX_ROUNDS:
                _exit_persist_if_last(suspended_exit=False)
                logger.info("AGENTIC topic %s done (round > %d)", topic, MAX_ROUNDS)
                return
            continue

        vendor = order[vi]
        context = get_agentic_topic_context(
            topic, draft_letter, cv_text, company_report, job_text, top_docs,
            style_instructions, additional_user_info,
        )
        _, updated_thread = _run_one_topic_agent(topic, vendor, context, thread_copy, trace_dir)

        with topic_lock:
            if "threads" not in state:
                state["threads"] = _empty_threads()
            state["threads"][topic] = updated_thread
            cur = state["topic_cursors"].get(topic) or cur
            cur["vendor_index"] = cur.get("vendor_index", 0) + 1
            order = cur.get("vendor_order") or []
            if cur["vendor_index"] >= len(order) and order:
                cur["vendor_index"] = 0
                cur["round"] = cur.get("round", 1) + 1
                random.shuffle(order)
            state["topic_cursors"][topic] = cur

        with topic_lock:
            cur = state["topic_cursors"].get(topic) or {}
        if cur.get("round", 1) > MAX_ROUNDS:
            _exit_persist_if_last(suspended_exit=False)
            logger.info("AGENTIC topic %s done (round > %d)", topic, MAX_ROUNDS)
            return


def _persist_agentic_from_live(session_key: str, state: Dict[str, Any]) -> None:
    """Write live agentic state back to session on disk."""
    try:
        data = load_session_from_storage(session_key)
        data["agentic"] = dict(state)
        save_session_to_storage(session_key, data)
    except Exception as e:
        logger.exception("AGENTIC persist from live failed: %s", e)


@router.get("/agentic/feedback/poll/")
async def agentic_feedback_poll(session: Session = Depends(get_session)):
    logger.info("AGENTIC poll request")
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_key = session.session_key
    if not session_key:
        return poll_response(None)
    now = time.time()
    entry = _get_agentic_live(session_key)
    if entry:
        state = entry["state"]
        with entry["meta_lock"]:
            state["last_poll_at"] = now
        persist_agentic_last_poll_at(session_key, now)
        snapshot = {}
        for topic in AGENTIC_TOPIC_KEYS:
            with entry["topic_locks"][topic]:
                threads = state.get("threads") or _empty_threads()
                topic_cursors = state.get("topic_cursors") or {}
                if "threads" not in snapshot:
                    snapshot["threads"] = {}
                    snapshot["topic_cursors"] = {}
                snapshot["threads"][topic] = list((threads.get(topic) or []))
                snapshot["topic_cursors"][topic] = dict((topic_cursors.get(topic) or {}))
        for k in ("feedback_ongoing", "status", "round", "draft_letter", "final_letter", "cost", "draft_vendor", "feedback_suspended"):
            if k in state:
                snapshot[k] = state[k]
        snapshot["last_poll_at"] = now
        return poll_response(snapshot)
    if "agentic" not in session:
        session["agentic"] = {}
    session["agentic"]["last_poll_at"] = now
    persist_agentic_last_poll_at(session_key, now)
    state = get_agentic_state(session)
    return poll_response(state)


@router.post("/agentic/run-round/")
async def agentic_run_round(data: AgenticRunRoundRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.feedback_vendors:
        raise HTTPException(status_code=400, detail="feedback_vendors is required")
    try:
        state = run_agentic_feedback_round(session, feedback_vendors=data.feedback_vendors)
        return {"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _apply_suspend(state: Dict[str, Any], all_topics: bool, topics: Optional[List[str]]) -> None:
    """Apply suspend to state (live or session): all or per-topic."""
    if all_topics:
        state["feedback_suspended"] = True
        state["feedback_ongoing"] = False
        return
    if topics:
        state.setdefault("topic_cursors", {})
        for t in topics:
            if t in AGENTIC_TOPIC_KEYS:
                cur = state["topic_cursors"].setdefault(t, {})
                cur["suspended"] = True


def _apply_resume(state: Dict[str, Any], all_topics: bool, topics: Optional[List[str]]) -> List[str]:
    """Clear suspend flags; set feedback_ongoing=True. Return list of topic keys to spawn (round <= MAX_ROUNDS)."""
    state["feedback_suspended"] = False
    state["feedback_ongoing"] = True
    to_spawn = []
    cursors = state.get("topic_cursors") or {}
    if all_topics:
        for t in AGENTIC_TOPIC_KEYS:
            cur = cursors.get(t) or {}
            cur = dict(cur)
            cur.pop("suspended", None)
            if "topic_cursors" not in state:
                state["topic_cursors"] = {}
            state["topic_cursors"][t] = cur
            if cur.get("round", 1) <= MAX_ROUNDS:
                to_spawn.append(t)
    elif topics:
        for t in topics:
            if t not in AGENTIC_TOPIC_KEYS:
                continue
            if "topic_cursors" not in state:
                state["topic_cursors"] = {}
            cur = dict(state["topic_cursors"].get(t) or {})
            cur.pop("suspended", None)
            state["topic_cursors"][t] = cur
            if cur.get("round", 1) <= MAX_ROUNDS:
                to_spawn.append(t)
    return to_spawn


@router.post("/agentic/feedback/suspend/")
async def agentic_feedback_suspend(
    data: AgenticSuspendRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    set_current_request(request)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    all_topics = data.all is True
    topics = data.topics if (data.topics and not all_topics) else None
    if not all_topics and not topics:
        raise HTTPException(status_code=400, detail="Provide all=true or topics=[...]")
    session_key = session.session_key
    try:
        entry = _get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                _apply_suspend(state, all_topics, topics)
            if not all_topics:
                for t in topics or []:
                    if t in AGENTIC_TOPIC_KEYS:
                        with entry["topic_locks"][t]:
                            state.setdefault("topic_cursors", {})
                            state["topic_cursors"].setdefault(t, {})["suspended"] = True
            return poll_response(state)
        if not session_key:
            raise HTTPException(status_code=400, detail="No session")
        data_load = load_session_from_storage(session_key)
        state = copy.deepcopy((data_load.get("agentic") or {}))
        if not state or state.get("status") != "feedback":
            raise HTTPException(status_code=400, detail="No agentic feedback in progress")
        _apply_suspend(state, all_topics, topics)
        data_load["agentic"] = state
        save_session_to_storage(session_key, data_load)
        return poll_response(state)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/feedback/resume/")
async def agentic_feedback_resume(
    data: AgenticResumeRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    set_current_request(request)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    all_topics = data.all is True
    topics = data.topics if (data.topics and not all_topics) else None
    if not all_topics and not topics:
        raise HTTPException(status_code=400, detail="Provide all=true or topics=[...]")
    session_key = session.session_key
    try:
        entry = _get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                to_spawn = _apply_resume(state, all_topics, topics)
            entry["running_count"] += len(to_spawn)
            loop = asyncio.get_event_loop()
            for topic in to_spawn:
                future = loop.run_in_executor(_feedback_executor, _run_topic_loop, session_key, topic)

                def _on_done(f, sk=session_key, t=topic):
                    try:
                        f.result()
                    except Exception:
                        logger.exception("AGENTIC topic %s resume failed for session %s", t, sk)

                future.add_done_callback(_on_done)
            return poll_response(state)
        data_load = load_session_from_storage(session_key) if session_key else None
        if not data_load or "agentic" not in data_load:
            raise HTTPException(status_code=400, detail="No agentic state to resume")
        state = copy.deepcopy(data_load["agentic"])
        state.setdefault("threads", _empty_threads())
        state.setdefault("topic_cursors", {})
        _get_topic_cursors(state)
        to_spawn = _apply_resume(state, all_topics, topics)
        if not to_spawn:
            if session_key:
                data_load["agentic"] = state
                save_session_to_storage(session_key, data_load)
            return poll_response(state)
        with _agentic_live_store_lock:
            if _agentic_live_store.get(session_key) is not None:
                raise HTTPException(status_code=409, detail="Feedback already running")
            entry = {
                "state": state,
                "topic_locks": {t: Lock() for t in AGENTIC_TOPIC_KEYS},
                "meta_lock": Lock(),
                "running_count": len(to_spawn),
            }
            _agentic_live_store[session_key] = entry
        persist_agentic_last_poll_at(session_key, time.time())
        loop = asyncio.get_event_loop()
        for topic in to_spawn:
            future = loop.run_in_executor(_feedback_executor, _run_topic_loop, session_key, topic)

            def _on_done(f, sk=session_key, t=topic):
                try:
                    f.result()
                except Exception:
                    logger.exception("AGENTIC topic %s resume failed for session %s", t, sk)

            future.add_done_callback(_on_done)
        return poll_response(state)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("AGENTIC resume failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/refine/")
async def agentic_refine(request: Request, session: Session = Depends(get_session), body: Optional[AgenticRefineRequest] = Body(None)):
    set_current_request(request)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        threads_override = body.threads if body and body.threads is not None else None
        state = run_agentic_refine(session, threads_override=threads_override)
        return {"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
