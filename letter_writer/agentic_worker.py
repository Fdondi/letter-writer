"""Background agentic feedback worker and in-memory live state."""

from __future__ import annotations

import copy
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, cast

from letter_writer.agentic_service import (
    DEFAULT_MAX_ROUNDS,
    PHASES_SUBCOMMENT_ADD,
    PHASES_SUBCOMMENT_VOTE,
    PHASE_A1,
    PHASE_A3,
    PHASE_B,
    STATUS_DRAFT,
    STATUS_FEEDBACK,
    STATUS_FEEDBACK_DONE,
    _empty_threads,
    _get_sub_comment_rounds,
    _get_topic_cursors,
    apply_phase_a1_comment,
    apply_phase_addendums,
    apply_phase_subcomment_votes,
    apply_phase_subcomments,
    apply_global_votes_and_prune,
    agentic_topic_human_label,
    build_agentic_phase_a_labels,
    build_phase_b_schema_for_topic,
    build_phase_subcomment_vote_schema,
    call_agentic_phase_action,
    clear_phase_progress,
    format_topic_thread_for_voting,
    prune_downvoted_subcomments,
)
from letter_writer.clients.base import ModelVendor
from letter_writer.feedback_checks import get_agentic_topic_context
from letter_writer.feedback_topics import AGENTIC_TOPIC_KEYS
from letter_writer.instructions import get_style_instructions
from letter_writer.phased_service import get_effective_additional_user_info, get_metadata_field
from letter_writer_server.core.session import (
    get_agentic_last_poll_at_from_storage,
    load_session_from_storage,
    save_agentic_state_to_storage,
    save_agentic_topic_slice_to_storage,
)

logger = logging.getLogger(__name__)

_feedback_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentic_feedback")

_agentic_live_store: Dict[str, Dict[str, Any]] = {}
_agentic_live_store_lock = Lock()


def get_agentic_live(session_key: str) -> Optional[Dict[str, Any]]:
    """Return the live agentic entry for this session if any."""
    with _agentic_live_store_lock:
        return _agentic_live_store.get(session_key)


def create_agentic_live(session_key: str, initial_agentic_state: Dict[str, Any]) -> Dict[str, Any]:
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


def remove_agentic_live(session_key: str) -> None:
    """Stop feedback and drop in-memory live entry (e.g. on session clear)."""
    entry = get_agentic_live(session_key)
    if entry:
        with entry["meta_lock"]:
            entry["state"]["feedback_ongoing"] = False
            entry["state"]["worker_running"] = False
        with _agentic_live_store_lock:
            _agentic_live_store.pop(session_key, None)


def launch_feedback_worker(session_key: str, entry: Dict[str, Any]) -> None:
    """Launch the background worker and ensure worker_running is reset on crash."""
    future = _feedback_executor.submit(_run_ordered_feedback_loop, session_key)

    def _on_done(fut: Any, sk: str = session_key) -> None:
        try:
            fut.result()
        except Exception:
            logger.exception("AGENTIC ordered worker failed for session %s", sk)
            curr_entry = get_agentic_live(sk)
            if curr_entry:
                with curr_entry["meta_lock"]:
                    curr_entry["state"]["worker_running"] = False
                    persist_agentic_from_live(sk, curr_entry["state"])

    future.add_done_callback(_on_done)


def _init_phase_a_progress(
    state: Dict[str, Any],
    topic: str,
    phase_label: str,
    round_num: int,
    feedback_vendors: List[str],
) -> None:
    """Initialise all vendor tasks for one topic's Phase-A sub-phase as pending (False)."""
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
    entry = get_agentic_live(session_key)
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
            persist_agentic_from_live(session_key, state)

    while True:
        with meta_lock:
            if not state.get("feedback_ongoing"):
                state["worker_running"] = False
                clear_phase_progress(state)
                persist_agentic_from_live(session_key, state)
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
                persist_agentic_from_live(session_key, state)
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
                persist_agentic_from_live(session_key, state)
            return
        if not feedback_vendors:
            _stop_feedback_worker()
            return

        persisted = load_session_from_storage(session_key)
        uid = (persisted.get("user") or {}).get("id") if isinstance(persisted, dict) else None
        additional_user_info = get_effective_additional_user_info(
            metadata, ModelVendor(draft_vendor), uid
        )
        hire_problem = str(get_metadata_field(metadata, ModelVendor(draft_vendor), "hire_problem", "") or "")
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
                hire_problem=hire_problem,
            )
            for t in active_topics
        }
        round_num = min(rounds.get(t, 1) for t in active_topics)

        phase_labels = build_agentic_phase_a_labels(sub_comment_rounds_cfg)
        topic_phase_status: Dict[str, str] = {t: phase_labels[0][1] for t in active_topics}

        def _run_topic_pipeline(topic: str) -> None:
            """Run one topic through all Phase-A sub-phases sequentially."""
            with meta_lock:
                cur = topic_cursors.get(topic) or {}
                resume_from = int(cur.get("last_completed_phase_idx", -1)) + 1
            for phase_idx, (phase_key, phase_label) in enumerate(phase_labels):
                if phase_idx < resume_from:
                    continue
                with meta_lock:
                    topic_phase_status[topic] = phase_label
                    thread_snapshot = copy.deepcopy(threads.get(topic) or [])

                vendor_results: List[Tuple[str, Dict[str, Any]]] = []
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
                        with meta_lock:
                            _mark_phase_a_done(state, topic, vendor)

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
                    cur = topic_cursors.setdefault(topic, {})
                    cur["last_completed_phase_idx"] = phase_idx
                    state["topic_cursors"] = topic_cursors
                    state["threads"] = threads
                    save_agentic_topic_slice_to_storage(
                        session_key, topic, threads.get(topic), cur
                    )

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

        with meta_lock:
            per_topic_threads_str: Dict[str, str] = {}
            per_topic_schema: Dict[str, Dict[str, Any]] = {}
            for t in active_topics:
                t_thread = threads.get(t) or []
                per_topic_threads_str[t] = format_topic_thread_for_voting(t_thread, t)
                per_topic_schema[t] = build_phase_b_schema_for_topic(t_thread, t)

        vote_tuples: List[Tuple[str, str, str]] = []
        for vendor in feedback_vendors:
            for source_topic in active_topics:
                for target_topic in active_topics:
                    vote_tuples.append((vendor, source_topic, target_topic))

        with meta_lock:
            _init_phase_b_progress(state, round_num, vote_tuples)

        vote_results: List[Tuple[str, str, Dict[str, Any]]] = []
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
                with meta_lock:
                    _mark_phase_b_done(state, vendor, source_topic, target_topic)

        with meta_lock:
            apply_global_votes_and_prune(threads, vote_results, round_num=round_num)
            for topic in active_topics:
                cur = dict(topic_cursors.get(topic) or {"round": 1, "vendor_index": 0, "vendor_order": []})
                cur["round"] = int(cur.get("round", 1)) + 1
                cur["vendor_index"] = 0
                cur.pop("last_completed_phase_idx", None)
                order = list(cur.get("vendor_order") or feedback_vendors)
                if order:
                    random.shuffle(order)
                    cur["vendor_order"] = order
                topic_cursors[topic] = cur
            state["threads"] = threads
            state["topic_cursors"] = topic_cursors
            persist_agentic_from_live(session_key, state)


def persist_agentic_from_live(session_key: str, state: Dict[str, Any]) -> None:
    """Write live agentic state back to session on disk."""
    try:
        save_agentic_state_to_storage(session_key, state)
    except Exception as e:
        logger.exception("AGENTIC persist from live failed: %s", e)


def has_pending_feedback(state: Dict[str, Any]) -> bool:
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


def start_ordered_worker(session_key: str) -> None:
    future = _feedback_executor.submit(_run_ordered_feedback_loop, session_key)

    def _on_done(fut: Any, sk: str = session_key) -> None:
        try:
            fut.result()
        except Exception:
            logger.exception("AGENTIC ordered worker failed for session %s", sk)

    future.add_done_callback(_on_done)
