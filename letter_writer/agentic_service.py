"""
Per-topic agentic flow: one draft model, feedback threads per topic (instruction, accuracy, etc.),
multiple feedback agents in random order per round, comments/subcomments/addendums/votes, then rewrite.
"""
from __future__ import annotations

import json
import logging
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log with timestamp so agentic flow is visible in uvicorn/server logs."""
    logger.info(msg)

from .client import get_client
from .clients.base import ModelVendor, ModelSize
from .generation import (
    AGENTIC_TOPIC_KEYS,
    get_agentic_topic_context,
    get_style_instructions,
    generate_letter,
    is_agentic_skip,
    rewrite_letter,
)
from .phased_service import get_metadata_field
from .retrieval import select_top_documents
from .research import company_research


# Status values for agentic state
STATUS_DRAFT = "draft"
STATUS_FEEDBACK = "feedback"
STATUS_FEEDBACK_DONE = "feedback_done"
STATUS_DONE = "done"

MAX_ROUNDS = 5
MAX_POSITIVE_COMMENTS = 5
MIN_ROUNDS_BEFORE_DONE = 2  # require at least 2 full rounds (2 interactions per vendor) before we can stop
# If the client does not send a poll request for this many seconds, we abort (client likely left).
# This is about browser not polling, not about agents taking long to respond.
POLL_ABORT_SECONDS = 30


def _require_session(session) -> None:
    """Raise if session is missing or invalid."""
    if not session:
        raise ValueError("Session is required")


def get_agentic_state(session) -> Optional[Dict[str, Any]]:
    """Return current agentic state from session dict, or None."""
    return session.get("agentic")


def save_agentic_state(session, state: Dict[str, Any]) -> None:
    """Persist agentic state into session. Assign a copy so session is definitely marked dirty and saved."""
    # Use a copy so middleware sees a write (in-place mutation of session["agentic"] doesn't trigger __setitem__)
    session["agentic"] = dict(state)


# Keys to send to the frontend (no cv_text, job_text, top_docs, company_report, metadata, style_instructions)
AGENTIC_STATE_RESPONSE_KEYS = ("status", "round", "draft_letter", "final_letter", "threads", "cost", "draft_vendor", "feedback_suspended", "topic_meta")


def _build_topic_meta(state: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build per-topic meta for UI: round, messages, suspended, done (round > MAX_ROUNDS)."""
    if not state:
        return {}
    threads = state.get("threads") or _empty_threads()
    cursors = state.get("topic_cursors") or {}
    global_suspended = bool(state.get("feedback_suspended"))
    out = {}
    for topic in AGENTIC_TOPIC_KEYS:
        cur = cursors.get(topic) or {}
        r = cur.get("round", 1)
        suspended = global_suspended or bool(cur.get("suspended"))
        done = r > MAX_ROUNDS
        out[topic] = {
            "round": r,
            "messages": len(threads.get(topic) or []),
            "suspended": suspended,
            "done": done,
        }
    return out


def slim_agentic_state_for_response(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a minimal state for API responses so we don't send cached heavy data."""
    if state is None:
        return None
    result = {k: state.get(k) for k in AGENTIC_STATE_RESPONSE_KEYS if k in state}
    result["topic_meta"] = _build_topic_meta(state)
    if "feedback_suspended" not in result and state.get("feedback_suspended") is not None:
        result["feedback_suspended"] = state.get("feedback_suspended")
    return result


def poll_response(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Minimal poll response: threads, ongoing, status, feedback_suspended, topic_meta.
    ongoing is taken only from persisted state; it is set true until all topic threads have signalled done (or suspend/abort).
    """
    state = state or {}
    threads = state.get("threads") or _empty_threads()
    ongoing = bool(state.get("feedback_ongoing"))
    status = state.get("status", STATUS_DRAFT)
    feedback_suspended = bool(state.get("feedback_suspended"))
    topic_meta = _build_topic_meta(state)
    return {
        "threads": threads,
        "ongoing": ongoing,
        "status": status,
        "feedback_suspended": feedback_suspended,
        "topic_meta": topic_meta,
    }


def _empty_threads() -> Dict[str, List[Dict]]:
    return {topic: [] for topic in AGENTIC_TOPIC_KEYS}


def _ensure_agentic_state(session) -> Dict[str, Any]:
    state = get_agentic_state(session)
    if state is None:
        state = {
            "draft_letter": None,
            "draft_vendor": None,
            "round": 0,
            "status": STATUS_DRAFT,
            "threads": _empty_threads(),
            "cost": 0.0,
        }
        save_agentic_state(session, state)
    if "threads" not in state:
        state["threads"] = _empty_threads()
    return state


def _ensure_addendum_id(a: Dict, comment_idx: int, addendum_idx: int) -> Dict:
    """Ensure addendum has an id (for referencing when upvoting). Mutates and returns a."""
    if not a.get("id"):
        a["id"] = f"a{comment_idx}_{addendum_idx}"
    return a


def _format_thread_for_prompt(thread: List[Dict], topic: str) -> str:
    """Format current thread (comments + addendums + votes + subcomments) for the prompt."""
    if not thread:
        return "(No comments yet.)"
    lines = []
    for i, c in enumerate(thread):
        cid = c.get("id", f"c{i}")
        lines.append(f"--- Comment {i+1} [id={cid}] by {c.get('vendor', '?')} ---")
        lines.append(c.get("text", ""))
        for ai, a in enumerate(c.get("addendums", [])):
            _ensure_addendum_id(a, i, ai)
            aup = a.get("up") or []
            lines.append(f"  Addendum [id={a.get('id')}] by {a.get('vendor', '?')} (upvotes={len(aup)}): {a.get('text', '')}")
        for s in c.get("subcomments", []):
            lines.append(f"  Reply by {s.get('vendor', '?')}: {s.get('text', '')}")
        up = c.get("votes", {}).get("up", [])
        down = c.get("votes", {}).get("down", [])
        lines.append(f"  Votes: up={len(up)} {up}, down={len(down)} {down}")
        lines.append("")
    return "\n".join(lines).strip()


def _agentic_feedback_prompt_first_agent(topic: str, context: str, topic_label: str) -> tuple:
    """System and user prompt for the first agent (no existing comments)."""
    system = (
        f"You are a feedback agent for the '{topic_label}' dimension of a cover letter. "
        "You see the draft letter and the relevant context. "
        "If you have substantive feedback (issues or suggestions for the draft), write it in a single comment. "
        "If you have nothing to add, output exactly: NO COMMENT (or SKIP). "
        "Do not add anything after NO COMMENT or SKIP. "
        "Your response must be either: (1) your feedback text, or (2) exactly 'NO COMMENT' or 'SKIP'."
    )
    prompt = (
        context + "\n\n"
        "Do you have any feedback on this draft for this dimension? "
        "Reply with your comment, or with NO COMMENT (or SKIP) if you have nothing to add."
    )
    return system, prompt


def _agentic_feedback_prompt_subsequent(
    topic: str, context: str, thread_str: str, topic_label: str
) -> tuple:
    """System and user prompt for agents that see existing comments."""
    system = (
        f"You are a feedback agent for the '{topic_label}' dimension. "
        "You see the draft, context, and the current thread (comments, addendums, replies, votes).\n\n"
        "Important distinction:\n"
        "- Comments and subcomments (replies) are for ephemeral discussion: use them to agree, disagree, or clarify. "
        "They are not passed to the draft revision. In subcomments it is fine to say 'I agree with that'; prefer novel insights when possible.\n"
        "- Addendums are the only content passed to the draft revision. Only addendums that receive at least one upvote are considered. "
        "Do NOT add a new addendum that repeats or rephrases another agent's suggestion—it is already in the thread. "
        "If you agree with an existing addendum, upvote it by addendum_id (no new text). Do NOT add an addendum that only says you agree to incorporate another addition; that is redundant.\n"
        "Add a new addendum ONLY when you have a significantly new, concrete, actionable revision suggestion (e.g. 'Add a sentence about X', "
        "'Rephrase paragraph 2 to emphasize Y'). The addendum field must be a concrete draft revision suggestion, not meta-commentary.\n\n"
        "You may: (1) add subcomments (replies) to any comment; (2) for each comment vote: upvote, upvote_addendum (with new addendum text or addendum_id to upvote existing), downvote, or none; "
        "(3) optionally add one new top-level comment. "
        "Respond with a single JSON object with keys: subcomments (list of {comment_id, text}), "
        "votes (list of {comment_id, action, addendum?: string, addendum_id?: string}), new_comment (string or null). "
        "Use comment 'id' for comment_id; use addendum 'id' for addendum_id when upvoting an existing addendum (omit addendum text in that case). "
        "If you do nothing, return {\"subcomments\": [], \"votes\": [], \"new_comment\": null}."
    )
    prompt = (
        context + "\n\n"
        "========== Current thread ==========\n" + thread_str + "\n\n"
        "Provide your response as JSON only (no markdown, no extra text)."
    )
    return system, prompt


def _topic_label(topic: str) -> str:
    return topic.replace("_", " ").title()


def _call_agentic_feedback_agent(
    vendor: str,
    topic: str,
    context: str,
    thread: List[Dict],
    trace_dir: Optional[Path],
) -> Dict[str, Any]:
    """
    Call one feedback agent for one topic. Returns parsed actions: subcomments, votes, new_comment.
    For first agent (empty thread), we do a simple text response; for subsequent, we ask for JSON.
    """
    client = get_client(ModelVendor(vendor))
    topic_label = _topic_label(topic)
    if not thread:
        system, prompt = _agentic_feedback_prompt_first_agent(topic, context, topic_label)
        raw = client.call(ModelSize.TINY, system, [prompt])
        raw = (raw or "").strip()
        if is_agentic_skip(raw):
            _log(f"AGENTIC {vendor} on {topic}: declined (NO COMMENT/SKIP)")
            return {"subcomments": [], "votes": [], "new_comment": None}
        return {"subcomments": [], "votes": [], "new_comment": raw}
    thread_str = _format_thread_for_prompt(thread, topic)
    system, prompt = _agentic_feedback_prompt_subsequent(topic, context, thread_str, topic_label)
    raw = client.call(ModelSize.TINY, system, [prompt])
    raw = (raw or "").strip()
    # Strip markdown code block if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"subcomments": [], "votes": [], "new_comment": None}
    subcomments = data.get("subcomments") or []
    votes = data.get("votes") or []
    new_comment = data.get("new_comment")
    if new_comment and isinstance(new_comment, str) and is_agentic_skip(new_comment):
        new_comment = None
    return {"subcomments": subcomments, "votes": votes, "new_comment": new_comment}


def _thread_addendum_by_id(thread: List[Dict]) -> Dict[str, Tuple[int, int]]:
    """Build addendum_id -> (comment_idx, addendum_idx). Ensures each addendum has an id."""
    out = {}
    for ci, c in enumerate(thread):
        for ai, a in enumerate(c.get("addendums", [])):
            _ensure_addendum_id(a, ci, ai)
            out[a["id"]] = (ci, ai)
    return out


def _apply_agent_response(
    thread: List[Dict],
    vendor: str,
    response: Dict[str, Any],
) -> bool:
    """
    Apply one agent's response to the thread. Returns True if any new content was added
    (new comment, new addendum, or new subcomment).
    """
    changed = False
    # Map comment id to index
    id_to_idx = {c.get("id"): i for i, c in enumerate(thread) if c.get("id")}
    addendum_by_id = _thread_addendum_by_id(thread)
    for sc in response.get("subcomments") or []:
        cid = sc.get("comment_id")
        if cid is None:
            for k in ("comment_id", "commentId"):
                if k in sc:
                    cid = sc[k]
                    break
        idx = id_to_idx.get(cid) if cid is not None else None
        if idx is not None:
            if "subcomments" not in thread[idx]:
                thread[idx]["subcomments"] = []
            thread[idx]["subcomments"].append({
                "id": str(uuid.uuid4())[:8],
                "vendor": vendor,
                "text": (sc.get("text") or sc.get("content") or "").strip(),
            })
            changed = True
    for v in response.get("votes") or []:
        cid = v.get("comment_id")
        if cid is None:
            cid = v.get("commentId")
        idx = id_to_idx.get(cid) if cid is not None else None
        if idx is None:
            continue
        action = (v.get("action") or "").lower()
        if "up" in action or action == "upvote":
            if "votes" not in thread[idx]:
                thread[idx]["votes"] = {"up": [], "down": []}
            if vendor not in thread[idx]["votes"]["up"]:
                thread[idx]["votes"]["up"].append(vendor)
                changed = True
            addendum_text = (v.get("addendum") or v.get("text") or "").strip()
            addendum_id = v.get("addendum_id") or v.get("addendumId")
            if addendum_id and not addendum_text:
                # Upvote existing addendum
                loc = addendum_by_id.get(addendum_id)
                if loc is not None:
                    ci, ai = loc
                    addendum = thread[ci]["addendums"][ai]
                    if "up" not in addendum:
                        addendum["up"] = []
                    if vendor not in addendum["up"]:
                        addendum["up"].append(vendor)
                        changed = True
            elif addendum_text and ("addendum" in action or "addendum" in v):
                # New addendum (author counts as first upvote)
                if "addendums" not in thread[idx]:
                    thread[idx]["addendums"] = []
                new_a = {
                    "id": str(uuid.uuid4())[:8],
                    "vendor": vendor,
                    "text": addendum_text,
                    "up": [vendor],
                }
                thread[idx]["addendums"].append(new_a)
                addendum_by_id[new_a["id"]] = (idx, len(thread[idx]["addendums"]) - 1)
                changed = True
        elif "down" in action or action == "downvote":
            if "votes" not in thread[idx]:
                thread[idx]["votes"] = {"up": [], "down": []}
            if vendor not in thread[idx]["votes"]["down"]:
                thread[idx]["votes"]["down"].append(vendor)
                changed = True
    new_comment = response.get("new_comment")
    if new_comment and isinstance(new_comment, str) and new_comment.strip():
        thread.append({
            "id": str(uuid.uuid4())[:8],
            "vendor": vendor,
            "text": new_comment.strip(),
            "addendums": [],
            "votes": {"up": [], "down": []},
            "subcomments": [],
        })
        changed = True
    return changed


def _count_positive_comments(threads: Dict[str, List[Dict]]) -> int:
    """Count comments that have net positive votes (more up than down) across all topics."""
    n = 0
    for thread in threads.values():
        for c in thread:
            up = len(c.get("votes", {}).get("up", []))
            down = len(c.get("votes", {}).get("down", []))
            if up > down:
                n += 1
    return n


def run_agentic_draft(
    session,
    draft_vendor: str,
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    style_instructions: str = "",
) -> Dict[str, Any]:
    """
    Generate the draft letter with the given vendor and store agentic state.
    Uses session common data; if company_report/top_docs not provided, runs background for draft_vendor.
    """
    _require_session(session)
    job_text = session.get("job_text", "")
    cv_text = session.get("cv_text", "")
    metadata = session.get("metadata", {})
    top_docs = top_docs_override if top_docs_override is not None else []
    company_report = company_report_override or ""

    if not company_report or not top_docs:
        vendor_enum = ModelVendor(draft_vendor)
        company_name = get_metadata_field(metadata, vendor_enum, "company_name", "Unknown")
        search_result = session.get("search_result", [])
        trace_dir = Path("trace", f"{company_name}.agentic.background")
        trace_dir.mkdir(parents=True, exist_ok=True)
        ai_client = get_client(vendor_enum)
        if search_result:
            result = select_top_documents(search_result, job_text, ai_client, trace_dir)
            top_docs = result.get("top_docs", [])
        if not company_report:
            point_of_contact = metadata.get("common", {}).get("point_of_contact")
            additional_company_info = get_metadata_field(metadata, vendor_enum, "additional_company_info", "")
            from .generation import get_search_instructions
            company_report = company_research(
                company_name, job_text, ai_client, trace_dir,
                point_of_contact=point_of_contact,
                additional_company_info=additional_company_info,
                search_instructions=get_search_instructions(),
            )

    if not style_instructions:
        style_instructions = session.get("style_instructions", "") or get_style_instructions()
    additional_user_info = get_metadata_field(metadata, ModelVendor(draft_vendor), "additional_user_info", "")

    trace_dir = Path("trace", "agentic.draft")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(ModelVendor(draft_vendor))
    draft_letter = generate_letter(
        cv_text, top_docs, company_report, job_text, ai_client, trace_dir,
        style_instructions, additional_user_info,
    )
    cost = getattr(ai_client, "total_cost", 0.0) or 0.0

    state = _ensure_agentic_state(session)
    state["draft_letter"] = draft_letter
    state["draft_vendor"] = draft_vendor
    state["round"] = 0
    state["status"] = STATUS_FEEDBACK
    state["threads"] = _empty_threads()
    state["cost"] = state.get("cost", 0) + cost
    state["top_docs"] = top_docs
    state["company_report"] = company_report
    state["job_text"] = job_text
    state["cv_text"] = cv_text
    state["metadata"] = metadata
    state["style_instructions"] = style_instructions
    save_agentic_state(session, state)
    return state


def run_agentic_feedback_round(
    session,
    feedback_vendors: List[str],
) -> Dict[str, Any]:
    """
    Run one round of feedback: for each topic, each vendor (in random order, no replacement)
    is called once. Updates threads and checks stop conditions.
    """
    _log("AGENTIC run_agentic_feedback_round: start")
    _require_session(session)
    state = get_agentic_state(session)
    if not state or state.get("status") != STATUS_FEEDBACK:
        raise ValueError("Agentic state missing or not in feedback phase")
    draft_letter = state.get("draft_letter") or ""
    draft_vendor = state.get("draft_vendor") or ""
    threads = state.get("threads") or _empty_threads()
    top_docs = state.get("top_docs") or []
    company_report = state.get("company_report") or ""
    job_text = state.get("job_text") or ""
    cv_text = state.get("cv_text") or ""
    metadata = state.get("metadata") or {}
    style_instructions = state.get("style_instructions") or get_style_instructions()
    additional_user_info = get_metadata_field(metadata, ModelVendor(draft_vendor), "additional_user_info", "")

    round_num = state.get("round", 0) + 1
    state["round"] = round_num
    any_change = False
    trace_dir = Path("trace", "agentic.feedback")
    trace_dir.mkdir(parents=True, exist_ok=True)

    for topic in AGENTIC_TOPIC_KEYS:
        context = get_agentic_topic_context(
            topic, draft_letter, cv_text, company_report, job_text, top_docs,
            style_instructions, additional_user_info,
        )
        thread = list(threads.get(topic, []))
        order = list(feedback_vendors)
        random.shuffle(order)
        for vendor in order:
            try:
                _log(f"AGENTIC feedback round {round_num}: topic={topic} vendor={vendor}")
                response = _call_agentic_feedback_agent(vendor, topic, context, thread, trace_dir)
                if _apply_agent_response(thread, vendor, response):
                    any_change = True
            except Exception as e:
                _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
        threads[topic] = thread
        state["threads"] = threads
        save_agentic_state(session, state)

    state["threads"] = threads
    positive_count = _count_positive_comments(threads)
    if not any_change or round_num >= MAX_ROUNDS or positive_count > MAX_POSITIVE_COMMENTS:
        state["status"] = STATUS_FEEDBACK_DONE
    save_agentic_state(session, state)
    return state


def _get_topic_cursors(state: Dict[str, Any], feedback_vendors: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Get or init per-topic cursors. Each topic has its own round, vendor_index, vendor_order (independent threads)."""
    cursors = state.get("topic_cursors")
    if cursors is not None and isinstance(cursors, dict):
        return cursors
    # Migrate from legacy single cursor
    order = state.get("feedback_vendor_order") or (list(feedback_vendors) if feedback_vendors else [])
    vi = state.get("next_vendor_index", 0)
    rnd = state.get("round", 1)
    cursors = {}
    for topic in AGENTIC_TOPIC_KEYS:
        o = list(order)
        random.shuffle(o)
        cursors[topic] = {"round": rnd, "vendor_index": vi, "vendor_order": o}
    state["topic_cursors"] = cursors
    return cursors


def start_agentic_feedback(session, feedback_vendors: List[str]) -> Dict[str, Any]:
    """Start poll-driven feedback: set feedback_ongoing, init per-topic cursors (each topic is an independent thread)."""
    _require_session(session)
    state = get_agentic_state(session)
    if not state or state.get("status") != STATUS_FEEDBACK:
        raise ValueError("Agentic state missing or not in feedback phase")
    state["feedback_ongoing"] = True
    state["last_poll_at"] = time.time()
    state["round"] = state.get("round", 0) + 1
    state["feedback_vendor_order"] = list(feedback_vendors)  # persist for migration / reload
    # Each topic gets its own memory: independent round index and shuffled vendor order
    state["topic_cursors"] = {
        topic: {
            "round": 1,
            "vendor_index": 0,
            "vendor_order": list(random.sample(feedback_vendors, len(feedback_vendors))),
        }
        for topic in AGENTIC_TOPIC_KEYS
    }
    save_agentic_state(session, state)
    return state


def _run_one_topic_agent(
    topic: str,
    vendor: str,
    context: str,
    thread_copy: List[Dict],
    trace_dir: Path,
) -> Tuple[str, List[Dict]]:
    """Run one feedback agent for one topic (used in thread pool). Writes only to thread_copy; returns (topic, thread)."""
    try:
        _log(f"AGENTIC topic={topic} vendor={vendor}")
        response = _call_agentic_feedback_agent(vendor, topic, context, thread_copy, trace_dir)
        _apply_agent_response(thread_copy, vendor, response)
    except Exception as e:
        _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
    return (topic, thread_copy)


def _run_one_topic_sequential(
    topic: str,
    context: str,
    thread: List[Dict],
    vendor_order: List[str],
    trace_dir: Path,
) -> Tuple[str, List[Dict]]:
    """Run all vendors for one topic sequentially so each agent sees previous addendums. Returns (topic, updated_thread)."""
    for vendor in vendor_order:
        try:
            _log(f"AGENTIC topic={topic} vendor={vendor} (sequential)")
            response = _call_agentic_feedback_agent(vendor, topic, context, thread, trace_dir)
            _apply_agent_response(thread, vendor, response)
        except Exception as e:
            _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
    return (topic, thread)


def run_agentic_feedback_step(
    session, last_poll_at_from_disk: Optional[float] = None
) -> Tuple[Dict[str, Any], bool]:
    """
    Run one full feedback round per poll: for each topic, run all vendors sequentially so each
    agent sees the previous agents' comments and addendums. Topics are processed in parallel.
    If no poll for 10s, abort. Returns (full state, ongoing).
    """
    _require_session(session)
    now = time.time()
    state = get_agentic_state(session)
    if not state:
        return (state or {}, False)
    if last_poll_at_from_disk is not None and (now - last_poll_at_from_disk) > POLL_ABORT_SECONDS:
        gap = now - last_poll_at_from_disk
        _log(f"AGENTIC feedback aborted: no poll from client for {gap:.1f}s (threshold {POLL_ABORT_SECONDS}s)")
        state["feedback_ongoing"] = False
        state["status"] = STATUS_FEEDBACK_DONE
        save_agentic_state(session, state)
        return (state, False)
    if not state.get("feedback_ongoing"):
        _log("AGENTIC poll step: early return (feedback_ongoing false)")
        return (state, False)

    cursors = state.get("topic_cursors") or {}
    entry_summary = {t: ((cursors.get(t) or {}).get("round", 1), (cursors.get(t) or {}).get("vendor_index", 0), len((cursors.get(t) or {}).get("vendor_order") or [])) for t in AGENTIC_TOPIC_KEYS}
    _log(f"AGENTIC poll step: entry feedback_ongoing=True per_topic(round,vi,order_len)={entry_summary}")

    draft_letter = state.get("draft_letter") or ""
    draft_vendor = state.get("draft_vendor") or ""
    threads = state.get("threads") or _empty_threads()
    top_docs = state.get("top_docs") or []
    company_report = state.get("company_report") or ""
    job_text = state.get("job_text") or ""
    cv_text = state.get("cv_text") or ""
    metadata = state.get("metadata") or {}
    style_instructions = state.get("style_instructions") or get_style_instructions()
    additional_user_info = get_metadata_field(metadata, ModelVendor(draft_vendor), "additional_user_info", "")
    topic_cursors = _get_topic_cursors(state)

    trace_dir = Path("trace", "agentic.feedback")
    trace_dir.mkdir(parents=True, exist_ok=True)

    # Ensure every topic has vendor_order (re-init from persisted list if empty, e.g. after reload)
    fallback_order = state.get("feedback_vendor_order") or []
    for topic in AGENTIC_TOPIC_KEYS:
        cur = topic_cursors.get(topic) or {"round": 1, "vendor_index": 0, "vendor_order": []}
        order = cur.get("vendor_order") or []
        if not order and fallback_order:
            cur["vendor_order"] = list(random.sample(fallback_order, len(fallback_order)))
            cur["vendor_index"] = 0
        topic_cursors[topic] = cur

    # Build one work item per topic: run all vendors for that topic sequentially so each sees prior addendums
    work = []
    for topic in AGENTIC_TOPIC_KEYS:
        cur = topic_cursors[topic]
        order = cur.get("vendor_order") or []
        if not order:
            continue
        context = get_agentic_topic_context(
            topic, draft_letter, cv_text, company_report, job_text, top_docs,
            style_instructions, additional_user_info,
        )
        # Copy thread so each topic's worker has its own list/dicts (no shared refs across parallel topics)
        thread_copy = []
        for c in (threads.get(topic) or []):
            nc = dict(c)
            nc["addendums"] = list(nc.get("addendums") or [])
            nc["subcomments"] = list(nc.get("subcomments") or [])
            v = nc.get("votes") or {}
            nc["votes"] = {"up": list(v.get("up", [])), "down": list(v.get("down", []))}
            thread_copy.append(nc)
        work.append((topic, context, thread_copy, order, trace_dir))

    if not work:
        # No topics have vendor_order (shouldn't happen after init). Advance rounds and re-check.
        for topic in AGENTIC_TOPIC_KEYS:
            cur = topic_cursors.get(topic) or {}
            order = cur.get("vendor_order") or []
            if order:
                cur["vendor_index"] = 0
                cur["round"] = cur.get("round", 1) + 1
                random.shuffle(order)
        rounds = {t: (topic_cursors.get(t) or {}).get("round", 1) for t in AGENTIC_TOPIC_KEYS}
        min_round = min(rounds.values())
        positive_count = _count_positive_comments(threads)
        all_topics_finished = all(r > MAX_ROUNDS for r in rounds.values())
        if min_round <= MIN_ROUNDS_BEFORE_DONE:
            _log(f"AGENTIC no work this poll, min_round={min_round} — not stopping (need all topics >{MAX_ROUNDS} or positive cap)")
        elif all_topics_finished or positive_count > MAX_POSITIVE_COMMENTS:
            state["feedback_ongoing"] = False
            state["status"] = STATUS_FEEDBACK_DONE
            _log(f"AGENTIC feedback done (all topics signalled): rounds={rounds} positive_count={positive_count}")
        save_agentic_state(session, state)
        return (state, state.get("feedback_ongoing", False))

    # Run each topic's full vendor sequence in parallel (within a topic, vendors run sequentially and see prior addendums)
    with ThreadPoolExecutor(max_workers=len(AGENTIC_TOPIC_KEYS)) as executor:
        futures = {
            executor.submit(_run_one_topic_sequential, t, c, th, order, trace_dir): t
            for (t, c, th, order, trace_dir) in work
        }
        for fut in as_completed(futures):
            topic, updated_thread = fut.result()
            threads[topic] = updated_thread
            cur = topic_cursors[topic]
            cur["vendor_index"] = 0
            cur["round"] = cur.get("round", 1) + 1
            order = cur.get("vendor_order") or []
            if order:
                random.shuffle(order)
                cur["vendor_order"] = order

    # Single write back to session state (no overwrite: we mutated state["threads"] and state["topic_cursors"] in place)
    state["threads"] = threads
    state["topic_cursors"] = topic_cursors

    rounds_per_topic = {t: (topic_cursors.get(t) or {}).get("round", 1) for t in AGENTIC_TOPIC_KEYS}
    min_round = min(rounds_per_topic.values())
    positive_count = _count_positive_comments(threads)
    _log(f"AGENTIC poll step: work_count={len(work)} min_round={min_round} rounds={rounds_per_topic}")

    # Ongoing becomes false only when every topic thread has signalled done (round > MAX_ROUNDS for all), or positive cap.
    # We never set done just because this poll ran — only when the state explicitly has all topics finished.
    all_topics_finished = all(r > MAX_ROUNDS for r in rounds_per_topic.values())
    if min_round <= MIN_ROUNDS_BEFORE_DONE:
        _log(f"AGENTIC not done: min_round={min_round} (need all topics >{MAX_ROUNDS} or positive cap)")
    elif all_topics_finished or positive_count > MAX_POSITIVE_COMMENTS:
        state["feedback_ongoing"] = False
        state["status"] = STATUS_FEEDBACK_DONE
        _log(f"AGENTIC feedback done (all topics signalled after work): rounds={rounds_per_topic} positive_count={positive_count}")

    save_agentic_state(session, state)
    ongoing = state.get("feedback_ongoing", False)
    _log(f"AGENTIC poll step: returning ongoing={ongoing} (saved to session)")
    return (state, ongoing)


def run_agentic_refine(session, threads_override: Optional[Dict[str, List[Dict]]] = None) -> Dict[str, Any]:
    """
    Collect all positive-vote comments and addendums, call rewrite with draft model, save final letter.
    Allow when status is feedback_done OR when feedback has stopped (feedback_ongoing false).
    If threads_override is provided, use it instead of state threads (e.g. user-edited).
    """
    _require_session(session)
    state = get_agentic_state(session)
    if not state:
        raise ValueError("Agentic state missing")
    # Allow refine when we've reached feedback_done, or when feedback has stopped (e.g. all topics done or 10s abort)
    if state.get("status") != STATUS_FEEDBACK_DONE and state.get("feedback_ongoing") is not False:
        raise ValueError("Agentic state missing or not in feedback_done phase")
    if state.get("status") != STATUS_FEEDBACK_DONE:
        state["status"] = STATUS_FEEDBACK_DONE  # align status so later code and UI stay consistent
    draft_letter = state.get("draft_letter") or ""
    draft_vendor = state.get("draft_vendor") or ""
    threads = threads_override if threads_override is not None else (state.get("threads") or _empty_threads())
    if threads_override is not None:
        state["threads"] = threads  # keep state in sync for any later use

    parts = []
    for topic in AGENTIC_TOPIC_KEYS:
        thread = threads.get(topic, [])
        for c in thread:
            up = len(c.get("votes", {}).get("up", []))
            down = len(c.get("votes", {}).get("down", []))
            if up <= down:
                continue
            label = _topic_label(topic)
            parts.append(f"[{label}] {c.get('text', '')}")
            for a in c.get("addendums", []):
                # Only include addendums that have at least one upvote (legacy addendums without "up" are still included)
                aup = a.get("up")
                if aup is not None and len(aup) == 0:
                    continue
                parts.append(f"  Addendum: {a.get('text', '')}")
    combined = "\n\n".join(parts) if parts else ""
    if not combined.strip():
        state["final_letter"] = draft_letter
        state["status"] = STATUS_DONE
        save_agentic_state(session, state)
        return state

    instruction_fb = combined
    accuracy_fb = "NO COMMENT"
    precision_fb = "NO COMMENT"
    company_fit_fb = "NO COMMENT"
    user_fit_fb = "NO COMMENT"
    human_fb = "NO COMMENT"
    trace_dir = Path("trace", "agentic.refine")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(ModelVendor(draft_vendor))
    final_letter = rewrite_letter(
        draft_letter,
        instruction_fb, accuracy_fb, precision_fb,
        company_fit_fb, user_fit_fb, human_fb,
        ai_client, trace_dir,
    )
    cost = getattr(ai_client, "total_cost", 0.0) or 0.0
    state["final_letter"] = final_letter
    state["status"] = STATUS_DONE
    state["cost"] = state.get("cost", 0) + cost
    save_agentic_state(session, state)
    return state
