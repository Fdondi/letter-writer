import copy
import logging
import time
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from letter_writer.generation import AGENTIC_TOPIC_KEYS
from letter_writer.agentic_service import (
    DEFAULT_MAX_ROUNDS,
    STATUS_FEEDBACK,
    _empty_threads,
    _get_topic_cursors,
    add_agentic_round,
    add_agentic_round_to_state,
    get_agentic_state,
    normalize_agentic_feedback_if_rounds_exhausted,
    poll_response,
    run_agentic_draft,
    run_agentic_draft_multi,
    run_agentic_refine,
    run_agentic_voting,
    slim_agentic_state_for_response,
    start_agentic_feedback,
    warn_agentic_round_limit_issues,
)
from letter_writer.agentic_worker import (
    _agentic_live_store,
    _agentic_live_store_lock,
    create_agentic_live,
    get_agentic_live,
    has_pending_feedback,
    launch_feedback_worker,
    persist_agentic_from_live,
    start_ordered_worker,
)
from letter_writer.firestore_store import get_user_data
from letter_writer.personal_data_sections import get_agentic_draft_model, get_models
from letter_writer.session_store import log_user_input_event, set_current_request
from letter_writer_server.api.cost_utils import check_spending_limits, with_user_monthly_cost
from letter_writer_server.core.session import (
    Session,
    get_session,
    load_session_from_storage,
    persist_agentic_last_poll_at,
    release_agentic_lock,
    require_auth,
    save_session_to_storage,
    try_acquire_agentic_lock,
)

router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)


class AgenticDraftRequest(BaseModel):
    """If draft_vendors is non-empty, one draft per vendor is generated (honors selection at top). Else single draft with draft_vendor."""
    draft_vendor: Optional[str] = None
    draft_vendors: Optional[List[str]] = None
    company_report: Optional[str] = None
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
            from letter_writer.clients.model_override import vendor_key_from_model_selector

            draft_vendor = vendor_key_from_model_selector(agentic_draft) or agentic_draft
        elif isinstance(default_models, list) and len(default_models) > 0:
            draft_vendor = default_models[0]
        else:
            draft_vendor = "openai"
    try:
        state = run_agentic_draft(
            session,
            draft_vendor=draft_vendor,
            company_report_override=data.company_report,
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
    entry = get_agentic_live(session_key) if session_key else None
    if entry:
        with entry["meta_lock"]:
            live_state = dict(entry["state"])
        merged = {**(state or {}), **{k: v for k, v in live_state.items() if v is not None}}
        state = merged
    elif session_key:
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
            start_poll_at = time.time()
            persist_agentic_last_poll_at(session_key, start_poll_at)
            entry = get_agentic_live(session_key)
            if entry is None:
                entry = create_agentic_live(session_key, state)
            else:
                with entry["meta_lock"]:
                    was_running = entry["state"].get("worker_running", False)
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
                    launch_feedback_worker(session_key, entry)
        return with_user_monthly_cost(poll_response(state), session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("AGENTIC feedback/start failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


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
    entry = get_agentic_live(session_key)
    if entry:
        live_state = entry["state"]
        with entry["meta_lock"]:
            live_state["last_poll_at"] = now
            should_auto_resume = (
                live_state.get("status") == STATUS_FEEDBACK
                and not bool(live_state.get("feedback_suspended"))
                and not bool(live_state.get("feedback_ongoing"))
                and not bool(live_state.get("worker_running"))
                and has_pending_feedback(live_state)
            )
            if should_auto_resume:
                live_state["feedback_ongoing"] = True
                live_state["worker_running"] = True
                persist_agentic_from_live(session_key, live_state)
                start_ordered_worker(session_key)
            if live_state and normalize_agentic_feedback_if_rounds_exhausted(live_state):
                persist_agentic_from_live(session_key, live_state)
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
                "worker_running",
                "phase_progress",
            ):
                if k in live_state:
                    snapshot[k] = live_state[k]
        persist_agentic_last_poll_at(session_key, now)
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
            and has_pending_feedback(poll_agentic)
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
                    and has_pending_feedback(poll_agentic)
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
                            start_ordered_worker(session_key)
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

    if poll_agentic and "threads" not in poll_agentic:
        poll_agentic["threads"] = _empty_threads()

    return with_user_monthly_cost(
        poll_response(poll_agentic),
        session,
    )


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
        entry = get_agentic_live(session_key) if session_key else None
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
        entry = get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                should_run = _apply_resume(state)
                can_start = should_run and not state.get("worker_running")
                if can_start:
                    state["worker_running"] = True
            if can_start:
                launch_feedback_worker(session_key, entry)
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
        launch_feedback_worker(session_key, entry)
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
        entry = get_agentic_live(session_key) if session_key else None
        if entry:
            state = entry["state"]
            with entry["meta_lock"]:
                add_agentic_round_to_state(state, all_topics=all_topics, topic=topic)
            persist_agentic_from_live(session_key, state)
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
