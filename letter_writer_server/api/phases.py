import asyncio
import copy
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from fastapi import APIRouter, Request, HTTPException, Depends, Body, Query
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
from letter_writer.agentic_service import (
    get_agentic_state,
    save_agentic_state,
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
    _run_one_topic_sequential,
    _get_topic_cursors,
    _empty_threads,
    get_prior_topic_top_comments,
    seed_thread_with_prior_topic_comments,
    merge_carryover_updates_and_strip,
    format_prior_topic_comments_for_prompt,
    DEFAULT_MAX_ROUNDS,
    POLL_ABORT_SECONDS,
    STATUS_DRAFT,
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
            user_id = (user or {}).get("id") or "anonymous"
            vendor_state = _run_background_phase(session.session_key, vendor_enum, common_data, user_id=user_id)
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
    max_rounds = data.max_rounds if data.max_rounds is not None else DEFAULT_MAX_ROUNDS
    draft_vendors = [v for v in (data.draft_vendors or []) if v]
    if draft_vendors:
        try:
            state = run_agentic_draft_multi(
                session,
                draft_vendors=draft_vendors,
                company_report_override=data.company_report,
                top_docs_override=data.top_docs,
                style_instructions=data.style_instructions or "",
                max_rounds=max_rounds,
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
            top_docs_override=data.top_docs,
            style_instructions=data.style_instructions or "",
            max_rounds=max_rounds,
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
            state["last_poll_at"] = start_poll_at
            save_agentic_state(session, state)
            persist_agentic_last_poll_at(session_key, start_poll_at)
            entry = _get_agentic_live(session_key)
            if entry is None:
                entry = _create_agentic_live(session_key, state)
            with entry["meta_lock"]:
                entry["state"]["last_poll_at"] = start_poll_at
                if not entry["state"].get("worker_running"):
                    entry["state"]["worker_running"] = True
                    loop = asyncio.get_event_loop()
                    future = loop.run_in_executor(_feedback_executor, _run_ordered_feedback_loop, session_key)

                    def _on_done(f, sk=session_key):
                        try:
                            f.result()
                        except Exception:
                            logger.exception("AGENTIC ordered worker failed for session %s", sk)

                    future.add_done_callback(_on_done)
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


def _get_agentic_live(session_key: str) -> Optional[Dict[str, Any]]:
    """Return the live agentic entry for this session if any."""
    with _agentic_live_store_lock:
        return _agentic_live_store.get(session_key)


def _create_agentic_live(session_key: str, initial_agentic_state: Dict[str, Any]) -> Dict[str, Any]:
    """Register in-memory state for ordered feedback loop. Returns the entry."""
    state = copy.deepcopy(initial_agentic_state)
    state.setdefault("threads", _empty_threads())
    state.setdefault("topic_cursors", {})
    _get_topic_cursors(state)
    entry = {
        "state": state,
        "meta_lock": Lock(),
        "worker_running": False,
    }
    with _agentic_live_store_lock:
        _agentic_live_store[session_key] = entry
    return entry


def _run_ordered_feedback_loop(session_key: str) -> None:
    """Run feedback in strict topic order so each topic sees prior-topic top comments."""
    entry = _get_agentic_live(session_key)
    if not entry:
        return
    state = entry["state"]
    meta_lock = entry["meta_lock"]
    trace_dir = Path("trace", "agentic.feedback")
    trace_dir.mkdir(parents=True, exist_ok=True)
    while True:
        now = time.time()
        with meta_lock:
            if not state.get("feedback_ongoing"):
                state["worker_running"] = False
                _persist_agentic_from_live(session_key, state)
                logger.info(
                    "AGENTIC ordered worker exit: ongoing=false session=%s",
                    session_key,
                )
                return
            last_poll_at_mem = float(state.get("last_poll_at") or 0.0)
            # Polls may hit another worker/process. Use persisted heartbeat too.
            try:
                last_poll_at_disk = float(get_agentic_last_poll_at_from_storage(session_key) or 0.0)
            except Exception:
                last_poll_at_disk = 0.0
            last_poll_at = max(last_poll_at_mem, last_poll_at_disk)
            state["last_poll_at"] = last_poll_at
            feedback_suspended = bool(state.get("feedback_suspended"))
            logger.info(
                "AGENTIC ordered tick: session=%s last_poll(mem=%.3f,disk=%.3f,use=%.3f) suspended=%s",
                session_key,
                last_poll_at_mem,
                last_poll_at_disk,
                last_poll_at,
                feedback_suspended,
            )
        if feedback_suspended:
            with meta_lock:
                state["feedback_ongoing"] = False
                state["worker_running"] = False
                _persist_agentic_from_live(session_key, state)
            logger.info("AGENTIC feedback suspended; ordered worker exits")
            return
        if (now - last_poll_at) > POLL_ABORT_SECONDS:
            logger.info(
                "AGENTIC feedback aborted: no poll from client for %.1fs (threshold %ds)",
                now - last_poll_at,
                POLL_ABORT_SECONDS,
            )
            with meta_lock:
                # Hard abort semantics: drop all feedback progress (past + future rounds).
                state["threads"] = _empty_threads()
                state["topic_cursors"] = {}
                state["round"] = 0
                state["feedback_ongoing"] = False
                state["feedback_suspended"] = False
                state["status"] = STATUS_DRAFT
                state.pop("feedback_vendor_order", None)
                state.pop("draft_votes", None)
                state["worker_running"] = False
                _persist_agentic_from_live(session_key, state)
            return

        with meta_lock:
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

        additional_user_info = get_metadata_field(
            metadata, ModelVendor(draft_vendor), "additional_user_info", ""
        )

        # Strict sequencing: fully complete one topic (all rounds) before moving to the next.
        with meta_lock:
            next_topic = None
            rounds = {
                t: int((topic_cursors.get(t) or {}).get("round", 1))
                for t in AGENTIC_TOPIC_KEYS
            }
            for t in AGENTIC_TOPIC_KEYS:
                if rounds.get(t, 1) <= max_rounds:
                    next_topic = t
                    break

        if next_topic is None:
            with meta_lock:
                state["feedback_ongoing"] = False
                state["status"] = STATUS_FEEDBACK_DONE
                state["worker_running"] = False
                _persist_agentic_from_live(session_key, state)
                logger.info("AGENTIC ordered feedback complete: rounds=%s", rounds)
            return

        topic = next_topic
        with meta_lock:
            cur = dict(topic_cursors.get(topic) or {"round": 1, "vendor_index": 0, "vendor_order": []})
            order = list(cur.get("vendor_order") or [])
            if not order:
                fallback = list(state.get("feedback_vendor_order") or [])
                if fallback:
                    random.shuffle(fallback)
                    order = fallback
                    cur["vendor_order"] = order
                    cur["vendor_index"] = 0
                    logger.info(
                        "AGENTIC topic vendor order initialized: session=%s topic=%s order=%s",
                        session_key,
                        topic,
                        order,
                    )
                else:
                    # No runnable vendors for this topic: mark topic complete so we can progress.
                    cur["round"] = max_rounds + 1
                    topic_cursors[topic] = cur
                    state["topic_cursors"] = topic_cursors
                    _persist_agentic_from_live(session_key, state)
                    logger.info(
                        "AGENTIC topic marked complete (no vendor order): session=%s topic=%s",
                        session_key,
                        topic,
                    )
                    continue
            thread = list(threads.get(topic) or [])
            logger.info(
                "AGENTIC topic start: session=%s topic=%s round=%s order_len=%s comments=%s",
                session_key,
                topic,
                cur.get("round", 1),
                len(order),
                len(thread),
            )

        prior_comments = get_prior_topic_top_comments(threads, topic)
        seed_thread_with_prior_topic_comments(thread, prior_comments)
        prior_comments_text = format_prior_topic_comments_for_prompt(prior_comments)
        logger.info(
            "AGENTIC topic carryover: session=%s topic=%s prior_comments=%s",
            session_key,
            topic,
            len(prior_comments),
        )

        context = get_agentic_topic_context(
            topic, draft_letter, cv_text, company_report, job_text, top_docs,
            style_instructions, additional_user_info,
            draft_letters=draft_letters_multi if len(draft_letters_multi) > 0 else None,
        )

        def _abort_for_stale_poll() -> bool:
            now_vendor = time.time()
            with meta_lock:
                last_poll_at_mem = float(state.get("last_poll_at") or 0.0)
            try:
                last_poll_at_disk = float(get_agentic_last_poll_at_from_storage(session_key) or 0.0)
            except Exception:
                last_poll_at_disk = 0.0
            last_poll_at = max(last_poll_at_mem, last_poll_at_disk)
            # If both heartbeat sources are unavailable, do not hard-abort this vendor call.
            # The outer loop still enforces abort semantics using heartbeat checks each tick.
            if last_poll_at <= 0.0:
                return False
            gap = now_vendor - last_poll_at
            if gap > POLL_ABORT_SECONDS:
                logger.info(
                    "AGENTIC feedback aborted before next vendor call: no poll from client for %.1fs (threshold %ds)",
                    gap,
                    POLL_ABORT_SECONDS,
                )
                return True
            return False

        _, updated_thread, topic_completed = _run_one_topic_sequential(
            topic,
            context,
            thread,
            order,
            trace_dir,
            prior_comments_text,
            should_abort=_abort_for_stale_poll,
        )

        if not topic_completed:
            with meta_lock:
                # Hard abort semantics: discard partial feedback generated so far.
                state["threads"] = _empty_threads()
                state["topic_cursors"] = {}
                state["round"] = 0
                state["feedback_ongoing"] = False
                state["feedback_suspended"] = False
                state["status"] = STATUS_DRAFT
                state.pop("feedback_vendor_order", None)
                state.pop("draft_votes", None)
                state["worker_running"] = False
                _persist_agentic_from_live(session_key, state)
            return

        with meta_lock:
            threads[topic] = merge_carryover_updates_and_strip(updated_thread, threads)
            old_round = int(cur.get("round", 1))
            cur["vendor_index"] = 0
            cur["round"] = old_round + 1
            order2 = list(cur.get("vendor_order") or [])
            if order2:
                random.shuffle(order2)
                cur["vendor_order"] = order2
            topic_cursors[topic] = cur
            state["threads"] = threads
            state["topic_cursors"] = topic_cursors
            # Persist after each topic update so polls on other workers
            # see monotonic round progression.
            _persist_agentic_from_live(session_key, state)
            logger.info(
                "AGENTIC topic persisted: session=%s topic=%s round %s->%s comments=%s",
                session_key,
                topic,
                old_round,
                cur["round"],
                len(updated_thread),
            )

        with meta_lock:
            _persist_agentic_from_live(session_key, state)


def _persist_agentic_from_live(session_key: str, state: Dict[str, Any]) -> None:
    """Write live agentic state back to session on disk."""
    try:
        data = load_session_from_storage(session_key)
        data["agentic"] = dict(state)
        save_session_to_storage(session_key, data)
    except Exception as e:
        logger.exception("AGENTIC persist from live failed: %s", e)


@router.get("/agentic/feedback/poll/")
async def agentic_feedback_poll(
    draft_letters_etag: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    logger.info("AGENTIC poll request")
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_key = session.session_key
    if not session_key:
        return with_user_monthly_cost(poll_response(None, known_draft_letters_etag=draft_letters_etag), session)
    now = time.time()
    entry = _get_agentic_live(session_key)
    if entry:
        state = entry["state"]
        with entry["meta_lock"]:
            state["last_poll_at"] = now
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
            ):
                if k in state:
                    snapshot[k] = state[k]
        persist_agentic_last_poll_at(session_key, now)
        rounds_live = {
            t: int(((snapshot.get("topic_cursors") or {}).get(t) or {}).get("round", 1))
            for t in AGENTIC_TOPIC_KEYS
        }
        logger.info(
            "AGENTIC poll source=live session=%s ongoing=%s status=%s rounds=%s",
            session_key,
            snapshot.get("feedback_ongoing"),
            snapshot.get("status"),
            rounds_live,
        )
        return with_user_monthly_cost(
            poll_response(snapshot, known_draft_letters_etag=draft_letters_etag),
            session,
        )
    if "agentic" not in session:
        session["agentic"] = {}
    session["agentic"]["last_poll_at"] = now
    persist_agentic_last_poll_at(session_key, now)
    try:
        persisted = load_session_from_storage(session_key) if session_key else None
        state = (persisted or {}).get("agentic") or get_agentic_state(session)
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
    return with_user_monthly_cost(
        poll_response(state, known_draft_letters_etag=draft_letters_etag),
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
                loop = asyncio.get_event_loop()
                future = loop.run_in_executor(_feedback_executor, _run_ordered_feedback_loop, session_key)

                def _on_done(f, sk=session_key):
                    try:
                        f.result()
                    except Exception:
                        logger.exception("AGENTIC ordered resume worker failed for session %s", sk)

                future.add_done_callback(_on_done)
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
            entry = {
                "state": state,
                "meta_lock": Lock(),
                "worker_running": True,
            }
            _agentic_live_store[session_key] = entry
        persist_agentic_last_poll_at(session_key, time.time())
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(_feedback_executor, _run_ordered_feedback_loop, session_key)

        def _on_done(f, sk=session_key):
            try:
                f.result()
            except Exception:
                logger.exception("AGENTIC ordered resume worker failed for session %s", sk)

        future.add_done_callback(_on_done)
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
    try:
        entry = _get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                add_agentic_round_to_state(state, all_topics=all_topics, topic=topic)
            _persist_agentic_from_live(session_key, state)
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
        response = {
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
        response = {
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
