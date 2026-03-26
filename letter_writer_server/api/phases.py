import asyncio
import copy
import logging
import random
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from typing import Dict, Any, List, Optional, Set, Tuple, cast
from pydantic import BaseModel

from letter_writer_server.core.session import (
    Session,
    get_session,
    get_agentic_last_poll_at_from_storage,
    load_session_from_storage,
    save_session_to_storage,
    persist_agentic_last_poll_at,
    try_acquire_agentic_lock,
    release_agentic_lock,
)
from letter_writer.generation import AGENTIC_TOPIC_KEYS, get_agentic_topic_context, get_style_instructions
from letter_writer.phased_service import get_metadata_field
from letter_writer.clients.base import ModelVendor
from letter_writer_server.api.cost_utils import with_user_monthly_cost
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
    clear_topic_feedback_wait,
    PHASE_A1,
    PHASE_A2A,
    PHASE_A2B,
    PHASE_A3,
    PHASE_B,
    call_agentic_phase_action,
    apply_phase_a1_comment,
    apply_phase_subcomments,
    apply_phase_addendums,
    format_global_threads_for_voting,
    apply_global_votes_and_prune,
    DEFAULT_MAX_ROUNDS,
    POLL_ABORT_SECONDS,
    STATUS_DRAFT,
    STATUS_FEEDBACK,
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
    """If draft_vendors is non-empty, one draft per vendor is generated (honors selection at top). Else single draft with draft_vendor."""
    draft_vendor: Optional[str] = None
    draft_vendors: Optional[List[str]] = None
    company_report: Optional[str] = None
    # JSON bodies stay Dict[str, Any] at the boundary; cast to TopDocument in handlers (see typed_shapes).
    top_docs: Optional[List[Dict[str, Any]]] = None
    style_instructions: Optional[str] = None
    max_rounds: Optional[int] = None


class AgenticRunRoundRequest(BaseModel):
    feedback_vendors: List[str]


class AgenticRefineRequest(BaseModel):
    """Optional edited threads to use for the rewrite (user may have edited/removed comments)."""
    threads: Optional[Dict[str, List[Dict[str, Any]]]] = None


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
    user = session.get("user")
    session.clear()
    if user:
        session["user"] = user
    # Rotate to a brand-new session id while keeping authenticated user context.
    session.session_key = secrets.token_urlsafe(32)
    # Cost flush logic omitted for brevity/simplicity, can add later
    return {
        "status": "ok",
        "old_session_id": old_id,
        "new_session_id": session.session_key,
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
async def draft_phase(vendor: str, data: DraftPhaseRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
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
async def refine_phase(vendor: str, data: RefinePhaseRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
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


# --- Agentic (per-topic) flow ---

@router.post("/agentic/draft/")
async def agentic_draft(data: AgenticDraftRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
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
        )
        return with_user_monthly_cost({"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agentic/state/")
async def agentic_state(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    state = get_agentic_state(session)
    return with_user_monthly_cost({"status": "ok", "agentic_state": slim_agentic_state_for_response(state)}, session)


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
                    entry["state"].clear()
                    entry["state"].update(copy.deepcopy(state))
                    entry["state"]["worker_running"] = was_running
            with entry["meta_lock"]:
                entry["state"]["last_poll_at"] = start_poll_at
                if not entry["state"].get("worker_running"):
                    entry["state"]["worker_running"] = True
                    _launch_feedback_worker(session_key, entry)
        return with_user_monthly_cost(poll_response(state), session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


logger = logging.getLogger(__name__)

# Thread pool for background feedback workers.
_feedback_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentic_feedback")

# In-memory live state for feedback: same process, same RAM.
_agentic_live_store: Dict[str, Dict[str, Any]] = {}
_agentic_live_store_lock = Lock()


def _launch_feedback_worker(session_key: str, entry: Dict[str, Any]) -> None:
    """Launch the background worker and ensure worker_running is reset on crash."""
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(_feedback_executor, _run_ordered_feedback_loop, session_key)

    def _on_done(f, sk=session_key):
        try:
            f.result()
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


def _topic_wait_strings_phase_a(
    active_topics: List[str],
    feedback_vendors: List[str],
    phase_label: str,
    round_num: int,
    done_pairs: Set[Tuple[str, str]],
) -> Dict[str, str]:
    """One line per topic: which vendors returned vs still in flight for this phase."""
    out: Dict[str, str] = {}
    for t in active_topics:
        done_list = sorted(v for v in feedback_vendors if (t, v) in done_pairs)
        pending_list = sorted(v for v in feedback_vendors if (t, v) not in done_pairs)
        out[t] = (
            f"{phase_label} (r{round_num}) — "
            f"API returned: {', '.join(done_list) if done_list else 'none'} | "
            f"still running: {', '.join(pending_list) if pending_list else 'none'}"
        )
    return out


def _topic_wait_strings_phase_b(
    active_topics: List[str],
    feedback_vendors: List[str],
    round_num: int,
    done_vendors: Set[str],
) -> Dict[str, str]:
    """Same global vote progress shown on every active topic column."""
    done_list = sorted(done_vendors)
    pending_list = sorted(v for v in feedback_vendors if v not in done_vendors)
    msg = (
        f"Phase B: global cross-topic vote (r{round_num}) — "
        f"API returned: {', '.join(done_list) if done_list else 'none'} | "
        f"still running: {', '.join(pending_list) if pending_list else 'none'}"
    )
    return {t: msg for t in active_topics}


def _run_ordered_feedback_loop(session_key: str) -> None:
    """Run feedback in global rounds with strict concurrent phases A1/A2a/A2b/A3/B."""
    entry = _get_agentic_live(session_key)
    if not entry:
        return
    state = entry["state"]
    meta_lock = entry["meta_lock"]
    Path("trace", "agentic.feedback").mkdir(parents=True, exist_ok=True)

    def _stale_poll_gap() -> float:
        with meta_lock:
            last_poll_at_mem = float(state.get("last_poll_at") or 0.0)
        try:
            last_poll_at_disk = float(get_agentic_last_poll_at_from_storage(session_key) or 0.0)
        except Exception:
            last_poll_at_disk = 0.0
        last_poll_at = max(last_poll_at_mem, last_poll_at_disk)
        if last_poll_at <= 0.0:
            return 0.0
        return time.time() - last_poll_at

    def _stop_feedback_worker() -> None:
        with meta_lock:
            state["feedback_ongoing"] = False
            state["feedback_suspended"] = False
            if state.get("status") not in (STATUS_DRAFT, STATUS_FEEDBACK_DONE):
                state["status"] = STATUS_FEEDBACK
            state["worker_running"] = False
            clear_topic_feedback_wait(state)
            _persist_agentic_from_live(session_key, state)

    while True:
        now = time.time()
        with meta_lock:
            if not state.get("feedback_ongoing"):
                state["worker_running"] = False
                clear_topic_feedback_wait(state)
                _persist_agentic_from_live(session_key, state)
                return
            last_poll_at_mem = float(state.get("last_poll_at") or 0.0)
            try:
                last_poll_at_disk = float(get_agentic_last_poll_at_from_storage(session_key) or 0.0)
            except Exception:
                last_poll_at_disk = 0.0
            last_poll_at = max(last_poll_at_mem, last_poll_at_disk)
            state["last_poll_at"] = last_poll_at
            if bool(state.get("feedback_suspended")):
                state["feedback_ongoing"] = False
                state["worker_running"] = False
                clear_topic_feedback_wait(state)
                _persist_agentic_from_live(session_key, state)
                return
            if (now - last_poll_at) > POLL_ABORT_SECONDS:
                _stop_feedback_worker()
                return
            threads = state.get("threads") or _empty_threads()
            state["threads"] = threads
            topic_cursors = state.get("topic_cursors") or {}
            state["topic_cursors"] = topic_cursors
            max_rounds = int(state.get("max_rounds", DEFAULT_MAX_ROUNDS))
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
                clear_topic_feedback_wait(state)
                _persist_agentic_from_live(session_key, state)
            return
        if not feedback_vendors:
            _stop_feedback_worker()
            return

        additional_user_info = get_metadata_field(
            metadata, ModelVendor(draft_vendor), "additional_user_info", ""
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

        phase_labels = [
            (PHASE_A1, "Phase A1: top-level comments"),
            (PHASE_A2A, "Phase A2a: sub-comments pass 1"),
            (PHASE_A2B, "Phase A2b: sub-comments pass 2"),
            (PHASE_A3, "Phase A3: edit suggestions"),
        ]
        for phase_key, phase_label in phase_labels:
            if _stale_poll_gap() > POLL_ABORT_SECONDS:
                _stop_feedback_worker()
                return
            with meta_lock:
                snapshot_threads = {t: copy.deepcopy(threads.get(t) or []) for t in active_topics}
                state["topic_feedback_wait"] = _topic_wait_strings_phase_a(
                    active_topics, feedback_vendors, phase_label, round_num, set()
                )

            phase_jobs = []
            for topic in active_topics:
                for vendor in feedback_vendors:
                    phase_jobs.append((topic, vendor, topic_contexts[topic], snapshot_threads[topic]))
            results: List[Tuple[str, str, Dict[str, Any]]] = []
            done_pairs: Set[Tuple[str, str]] = set()
            with ThreadPoolExecutor(max_workers=max(1, len(phase_jobs))) as executor:
                phase_a_futures = {
                    executor.submit(
                        call_agentic_phase_action,
                        vendor=vendor,
                        phase=phase_key,
                        topic=topic,
                        context=context,
                        thread=thread_snapshot,
                    ): (topic, vendor)
                    for (topic, vendor, context, thread_snapshot) in phase_jobs
                }
                for fut in as_completed(phase_a_futures):
                    topic, vendor = phase_a_futures[fut]
                    try:
                        payload = fut.result() or {}
                    except Exception as e:
                        logger.exception(
                            "AGENTIC phase error phase=%s topic=%s vendor=%s err=%s",
                            phase_key,
                            topic,
                            vendor,
                            e,
                        )
                        payload = {}
                    results.append((topic, vendor, payload))
                    done_pairs.add((topic, vendor))
                    with meta_lock:
                        state["topic_feedback_wait"] = _topic_wait_strings_phase_a(
                            active_topics,
                            feedback_vendors,
                            phase_label,
                            round_num,
                            done_pairs,
                        )

            with meta_lock:
                for topic, vendor, payload in results:
                    thread = threads.get(topic) or []
                    if phase_key == PHASE_A1:
                        apply_phase_a1_comment(thread, vendor, payload.get("new_comment"), round_num=round_num)
                    elif phase_key in (PHASE_A2A, PHASE_A2B):
                        apply_phase_subcomments(thread, vendor, payload.get("subcomments") or [])
                    elif phase_key == PHASE_A3:
                        apply_phase_addendums(thread, vendor, payload.get("addendums") or [])
                    threads[topic] = thread
                state["threads"] = threads
                _persist_agentic_from_live(session_key, state)

        if _stale_poll_gap() > POLL_ABORT_SECONDS:
            _stop_feedback_worker()
            return

        with meta_lock:
            state["topic_feedback_wait"] = _topic_wait_strings_phase_b(
                active_topics, feedback_vendors, round_num, set()
            )
            global_threads_str = format_global_threads_for_voting(threads, active_topics)

        global_context = (
            "Cross-topic voting context.\n\n"
            f"Job:\n{job_text}\n\n"
            f"Draft vendor: {draft_vendor}\n\n"
            f"Draft letter:\n{draft_letter}\n\n"
            f"Company report:\n{company_report}\n"
        )
        vote_results: List[Tuple[str, Dict[str, Any]]] = []
        done_vote_vendors: Set[str] = set()
        with ThreadPoolExecutor(max_workers=max(1, len(feedback_vendors))) as executor:
            vote_futures = {
                executor.submit(
                    call_agentic_phase_action,
                    vendor=vendor,
                    phase=PHASE_B,
                    topic="global",
                    context=global_context,
                    global_threads_str=global_threads_str,
                ): vendor
                for vendor in feedback_vendors
            }
            for fut in as_completed(vote_futures):
                vote_vendor = vote_futures[fut]
                try:
                    payload = fut.result() or {}
                except Exception as e:
                    logger.exception("AGENTIC phase B error vendor=%s err=%s", vote_vendor, e)
                    payload = {}
                vote_results.append((vote_vendor, payload))
                done_vote_vendors.add(vote_vendor)
                with meta_lock:
                    state["topic_feedback_wait"] = _topic_wait_strings_phase_b(
                        active_topics, feedback_vendors, round_num, done_vote_vendors
                    )

        with meta_lock:
            apply_global_votes_and_prune(threads, vote_results, round_num=round_num)
            for topic in active_topics:
                cur = dict(topic_cursors.get(topic) or {"round": 1, "vendor_index": 0, "vendor_order": []})
                cur["round"] = int(cur.get("round", 1)) + 1
                cur["vendor_index"] = 0
                order = list(cur.get("vendor_order") or feedback_vendors)
                if order:
                    random.shuffle(order)
                    cur["vendor_order"] = order
                topic_cursors[topic] = cur
            state["threads"] = threads
            state["topic_cursors"] = topic_cursors
            _persist_agentic_from_live(session_key, state)


def _persist_agentic_from_live(session_key: str, state: Dict[str, Any]) -> None:
    """Write live agentic state back to session on disk."""
    try:
        data = load_session_from_storage(session_key)
        merged_state = dict(state)
        # Heartbeat is stored separately from agentic state; never persist it here.
        merged_state.pop("last_poll_at", None)
        data["agentic"] = merged_state
        save_session_to_storage(session_key, data)
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
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(_feedback_executor, _run_ordered_feedback_loop, session_key)

    def _on_done(f, sk=session_key):
        try:
            f.result()
        except Exception:
            logger.exception("AGENTIC ordered worker failed for session %s", sk)

    future.add_done_callback(_on_done)


@router.get("/agentic/feedback/poll/")
async def agentic_feedback_poll(
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
        state = entry["state"]
        with entry["meta_lock"]:
            state["last_poll_at"] = now
            should_auto_resume = (
                state.get("status") == STATUS_FEEDBACK
                and not bool(state.get("feedback_suspended"))
                and not bool(state.get("feedback_ongoing"))
                and not bool(state.get("worker_running"))
                and _has_pending_feedback(state)
            )
            if should_auto_resume:
                state["feedback_ongoing"] = True
                state["worker_running"] = True
                _persist_agentic_from_live(session_key, state)
                _start_ordered_worker(session_key)
            if normalize_agentic_feedback_if_rounds_exhausted(state):
                _persist_agentic_from_live(session_key, state)
            warn_agentic_round_limit_issues(state)
            snapshot = {
                "threads": copy.deepcopy(state.get("threads") or _empty_threads()),
                "topic_cursors": copy.deepcopy(state.get("topic_cursors") or {}),
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
                "draft_votes",
                # Required for poll_response / _build_topic_meta waiting_for (per-topic progress)
                "worker_running",
                "topic_feedback_wait",
            ):
                if k in state:
                    snapshot[k] = state[k]
        persist_agentic_last_poll_at(session_key, now)
        tc_raw = snapshot.get("topic_cursors")
        tc = tc_raw if isinstance(tc_raw, dict) else {}
        rounds_live = {}
        for t in AGENTIC_TOPIC_KEYS:
            cur_tc = tc.get(t)
            cur_dict = cur_tc if isinstance(cur_tc, dict) else {}
            rounds_live[t] = int(cur_dict.get("round", 1))
        logger.info(
            "AGENTIC poll source=live session=%s ongoing=%s status=%s rounds=%s",
            session_key,
            snapshot.get("feedback_ongoing"),
            snapshot.get("status"),
            rounds_live,
        )
        return with_user_monthly_cost(
            poll_response(snapshot),
            session,
        )
    if "agentic" not in session:
        session["agentic"] = {}
    persist_agentic_last_poll_at(session_key, now)
    try:
        persisted = load_session_from_storage(session_key) if session_key else None
        state = (persisted or {}).get("agentic") or get_agentic_state(session)
        should_auto_resume = (
            state
            and state.get("status") == STATUS_FEEDBACK
            and not bool(state.get("feedback_suspended"))
            and not bool(state.get("feedback_ongoing"))
            and _has_pending_feedback(state)
        )
        if should_auto_resume and try_acquire_agentic_lock(session_key, timeout_seconds=15.0):
            try:
                latest_payload = load_session_from_storage(session_key) if session_key else {}
                latest = (latest_payload or {}).get("agentic") or {}
                if latest:
                    state = latest
                if (
                    state
                    and state.get("status") == STATUS_FEEDBACK
                    and not bool(state.get("feedback_suspended"))
                    and not bool(state.get("feedback_ongoing"))
                    and _has_pending_feedback(state)
                ):
                    state = dict(state)
                    state["feedback_ongoing"] = True
                    state["worker_running"] = True
                    payload = latest_payload or {}
                    payload["agentic"] = state
                    save_session_to_storage(session_key, payload)
                    with _agentic_live_store_lock:
                        if _agentic_live_store.get(session_key) is None:
                            _agentic_live_store[session_key] = {
                                "state": state,
                                "meta_lock": Lock(),
                                "worker_running": True,
                            }
                            _start_ordered_worker(session_key)
            finally:
                release_agentic_lock(session_key)
        rounds_persisted = {
            t: int((((state or {}).get("topic_cursors") or {}).get(t) or {}).get("round", 1))
            for t in AGENTIC_TOPIC_KEYS
        }
        logger.info(
            "AGENTIC poll source=persisted session=%s ongoing=%s status=%s rounds=%s",
            session_key,
            (state or {}).get("feedback_ongoing"),
            (state or {}).get("status"),
            rounds_persisted,
        )
    except Exception:
        state = get_agentic_state(session)
        rounds_session = {
            t: int((((state or {}).get("topic_cursors") or {}).get(t) or {}).get("round", 1))
            for t in AGENTIC_TOPIC_KEYS
        }
        logger.info(
            "AGENTIC poll source=session-fallback session=%s ongoing=%s status=%s rounds=%s",
            session_key,
            (state or {}).get("feedback_ongoing"),
            (state or {}).get("status"),
            rounds_session,
        )
    if state and normalize_agentic_feedback_if_rounds_exhausted(state):
        payload = load_session_from_storage(session_key) if session_key else {}
        if not isinstance(payload, dict):
            payload = {}
        payload["agentic"] = state
        if session_key:
            save_session_to_storage(session_key, payload)
        session["agentic"] = state
    warn_agentic_round_limit_issues(state)
    return with_user_monthly_cost(
        poll_response(state),
        session,
    )


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
async def agentic_rounds_add(
    data: AgenticAddRoundRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    set_current_request(request)
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
async def agentic_vote(data: AgenticVoteRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
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
async def agentic_refine(request: Request, session: Session = Depends(get_session), body: Optional[AgenticRefineRequest] = Body(None)):
    set_current_request(request)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        threads_override = body.threads if body and body.threads is not None else None
        state = run_agentic_refine(session, threads_override=threads_override)
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
