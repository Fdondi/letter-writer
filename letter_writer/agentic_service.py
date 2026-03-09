"""
Per-topic agentic flow: one draft model, feedback threads per topic (instruction, accuracy, etc.),
multiple feedback agents in random order per round, comments/subcomments/addendums/votes, then rewrite.
"""
from __future__ import annotations

import json
import hashlib
import logging
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from .cost_tracker import track_api_cost
from .retrieval import select_top_documents
from .research import company_research


# Status values for agentic state
STATUS_DRAFT = "draft"
STATUS_FEEDBACK = "feedback"
STATUS_FEEDBACK_DONE = "feedback_done"
STATUS_DONE = "done"

DEFAULT_MAX_ROUNDS = 3
MAX_POSITIVE_COMMENTS = 5
MIN_ROUNDS_BEFORE_DONE = 2  # require at least 2 full rounds (2 interactions per vendor) before we can stop
# If the client does not send a poll request for this many seconds, we abort (client likely left).
# This is about browser not polling, not about agents taking long to respond.
POLL_ABORT_SECONDS = 30


def _require_session(session) -> None:
    """Raise if session is missing or invalid."""
    if not session:
        raise ValueError("Session is required")


def _user_id(session) -> str:
    """Return authenticated user id for cost tracking, or 'anonymous'."""
    return (session.get("user") or {}).get("id") or "anonymous"


def get_agentic_state(session) -> Optional[Dict[str, Any]]:
    """Return current agentic state from session dict, or None."""
    return session.get("agentic")


def save_agentic_state(session, state: Dict[str, Any]) -> None:
    """Persist agentic state into session. Assign a copy so session is definitely marked dirty and saved."""
    # Use a copy so middleware sees a write (in-place mutation of session["agentic"] doesn't trigger __setitem__)
    session["agentic"] = dict(state)


# Keys to send to the frontend (no cv_text, job_text, top_docs, company_report, metadata, style_instructions)
AGENTIC_STATE_RESPONSE_KEYS = (
    "status", "round", "draft_letter", "final_letter", "threads", "cost", "draft_vendor",
    "draft_letters", "final_letters", "feedback_suspended", "topic_meta", "max_rounds",
    "vendor_errors", "draft_votes", "refine_samples",
)


def _get_max_rounds(state: Optional[Dict[str, Any]]) -> int:
    """Return configured max_rounds for this run (default DEFAULT_MAX_ROUNDS)."""
    if not state:
        return DEFAULT_MAX_ROUNDS
    return int(state.get("max_rounds") or DEFAULT_MAX_ROUNDS)


def _build_topic_meta(state: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build per-topic meta for UI: round, messages, done (round > max_rounds)."""
    if not state:
        return {}
    threads = state.get("threads") or _empty_threads()
    cursors = state.get("topic_cursors") or {}
    max_rounds = _get_max_rounds(state)
    out = {}
    for topic in AGENTIC_TOPIC_KEYS:
        cur = cursors.get(topic) or {}
        r = cur.get("round", 1)
        done = r > max_rounds
        out[topic] = {
            "round": r,
            "messages": len(threads.get(topic) or []),
            "done": done,
        }
    return out


def slim_agentic_state_for_response(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a minimal state for API responses so we don't send cached heavy data."""
    if state is None:
        return None
    result = {k: state.get(k) for k in AGENTIC_STATE_RESPONSE_KEYS if k in state}
    result["topic_meta"] = _build_topic_meta(state)
    result["max_rounds"] = _get_max_rounds(state)
    if "feedback_suspended" not in result and state.get("feedback_suspended") is not None:
        result["feedback_suspended"] = state.get("feedback_suspended")
    return result


def _draft_letters_etag(draft_letters: Dict[str, Any]) -> str:
    """Stable hash for draft_letters payload comparison across polls."""
    payload = json.dumps(draft_letters, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def poll_response(
    state: Optional[Dict[str, Any]],
    known_draft_letters_etag: Optional[str] = None,
) -> Dict[str, Any]:
    """Minimal poll response: per-topic threads-with-meta, ongoing, status, feedback_suspended, and optionally draft/final letters.
    ongoing is taken only from persisted state; it is set true until all topic threads have signalled done (or suspend/abort).
    """
    state = state or {}
    raw_threads = state.get("threads") or _empty_threads()
    ongoing = bool(state.get("feedback_ongoing"))
    status = state.get("status", STATUS_DRAFT)
    feedback_suspended = bool(state.get("feedback_suspended"))
    topic_meta = _build_topic_meta(state)
    threads = {}
    for topic in AGENTIC_TOPIC_KEYS:
        threads[topic] = {
            "thread": list(raw_threads.get(topic) or []),
            "round": (topic_meta.get(topic) or {}).get("round", 1),
            "messages": (topic_meta.get(topic) or {}).get("messages", len(raw_threads.get(topic) or [])),
            "done": (topic_meta.get(topic) or {}).get("done", False),
        }
    out = {
        "threads": threads,
        "ongoing": ongoing,
        "status": status,
        "feedback_suspended": feedback_suspended,
        "max_rounds": _get_max_rounds(state),
    }
    draft_letters = state.get("draft_letters") or {}
    if draft_letters:
        draft_letters_etag = _draft_letters_etag(draft_letters)
        out["draft_letters_etag"] = draft_letters_etag
        if not known_draft_letters_etag or known_draft_letters_etag != draft_letters_etag:
            out["draft_letters"] = draft_letters
    if state.get("final_letters"):
        out["final_letters"] = state["final_letters"]
    if state.get("draft_votes"):
        out["draft_votes"] = state["draft_votes"]
    return out


def _empty_threads() -> Dict[str, List[Dict]]:
    return {topic: [] for topic in AGENTIC_TOPIC_KEYS}


def _ensure_agentic_state(session) -> Dict[str, Any]:
    state = get_agentic_state(session)
    if state is None:
        state = {
            "draft_letter": None,
            "draft_letters": {},
            "draft_vendor": None,
            "round": 0,
            "status": STATUS_DRAFT,
            "threads": _empty_threads(),
            "cost": 0.0,
            "final_letter": None,
            "final_letters": {},
        }
        save_agentic_state(session, state)
    if "threads" not in state:
        state["threads"] = _empty_threads()
    if "draft_letters" not in state:
        state["draft_letters"] = state.get("draft_letters") or {}
    if "final_letters" not in state:
        state["final_letters"] = state.get("final_letters") or {}
    return state


def _ensure_addendum_id(a: Dict, comment_idx: int, addendum_idx: int) -> Dict:
    """Ensure addendum has an id (for referencing when upvoting). Mutates and returns a."""
    if not a.get("id"):
        a["id"] = f"a{comment_idx}_{addendum_idx}"
    return a


def _comment_acted_vendors(c: Dict) -> set:
    """Vendors who have acted on this comment (voted, subcommented, or added an addendum)."""
    acted = set()
    v = c.get("votes") or {}
    acted.update(v.get("up") or [])
    acted.update(v.get("down") or [])
    acted.update(v.get("abstain") or [])
    for s in c.get("subcomments", []):
        if s.get("vendor"):
            acted.add(s["vendor"])
    for a in c.get("addendums", []):
        if a.get("vendor"):
            acted.add(a["vendor"])
    return acted


def _sanitize_vote_reason(raw: Any) -> str:
    """Normalize optional model-provided vote rationale to a short one-liner."""
    if not isinstance(raw, str):
        return ""
    compact = " ".join(raw.strip().split())
    return compact[:180]


def _ensure_vote_round_bucket(c: Dict[str, Any], round_num: Optional[int]) -> Dict[str, Any]:
    """Return mutable per-round vote bucket for a comment."""
    rn = int(round_num or c.get("created_round") or 1)
    rounds = c.setdefault("votes_by_round", {})
    key = str(rn)
    bucket = rounds.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        rounds[key] = bucket
    bucket.setdefault("up", [])
    bucket.setdefault("down", [])
    bucket.setdefault("abstain", [])
    bucket.setdefault("reasons", {})
    return bucket


def _set_comment_vote_action(
    c: Dict[str, Any],
    vendor: str,
    action: str,
    *,
    round_num: Optional[int] = None,
    reason: str = "",
) -> bool:
    """
    Set one vendor vote action on a top-level comment.

    Keeps aggregate votes consistent (vendor appears in exactly one of up/down/abstain),
    and records a per-round snapshot + rationale for audit/UX.
    """
    if "votes" not in c or not isinstance(c.get("votes"), dict):
        c["votes"] = {"up": [], "down": [], "abstain": []}
    votes = c["votes"]
    votes.setdefault("up", [])
    votes.setdefault("down", [])
    votes.setdefault("abstain", [])
    changed = False

    for k in ("up", "down", "abstain"):
        if vendor in votes[k]:
            votes[k].remove(vendor)
            changed = True
    if vendor not in votes[action]:
        votes[action].append(vendor)
        changed = True

    bucket = _ensure_vote_round_bucket(c, round_num)
    for k in ("up", "down", "abstain"):
        if vendor in bucket[k]:
            bucket[k].remove(vendor)
            changed = True
    if vendor not in bucket[action]:
        bucket[action].append(vendor)
        changed = True

    bucket_reasons = bucket.setdefault("reasons", {})
    clean_reason = _sanitize_vote_reason(reason)
    if clean_reason:
        prev = bucket_reasons.get(vendor)
        if prev != clean_reason:
            bucket_reasons[vendor] = clean_reason
            changed = True

    return changed


def _is_comment_removed(c: Dict[str, Any]) -> bool:
    """A comment is removed forever for downstream use once any downvote is registered."""
    if c.get("removed"):
        return True
    down = c.get("votes", {}).get("down", [])
    return len(down) > 0


def _comment_score(c: Dict[str, Any]) -> float:
    """Ranking heuristic for 'top comments' carry-over."""
    votes = c.get("votes") or {}
    up = len(votes.get("up") or [])
    down = len(votes.get("down") or [])
    pos_add = 0
    for a in c.get("addendums", []):
        if len(a.get("up") or []) > len(a.get("down") or []):
            pos_add += 1
    return float((up - down) + 0.25 * len(c.get("subcomments") or []) + 0.35 * pos_add)


def _clone_comment_for_carryover(c: Dict[str, Any], *, carry_topic: str, carry_id: str) -> Dict[str, Any]:
    """Clone comment payload so downstream topics can vote/comment/add on prior-topic comments."""
    addendums = []
    for a in (c.get("addendums") or []):
        addendums.append({
            "id": a.get("id"),
            "vendor": a.get("vendor"),
            "text": a.get("text", ""),
            "up": list(a.get("up") or []),
            "down": list(a.get("down") or []),
        })
    subcomments = []
    for s in (c.get("subcomments") or []):
        subcomments.append({
            "id": s.get("id"),
            "vendor": s.get("vendor"),
            "text": s.get("text", ""),
        })
    votes = c.get("votes") or {}
    votes_by_round = c.get("votes_by_round") or {}
    vote_rounds_out = {}
    for round_key, bucket in votes_by_round.items():
        if not isinstance(bucket, dict):
            continue
        vote_rounds_out[str(round_key)] = {
            "up": list(bucket.get("up") or []),
            "down": list(bucket.get("down") or []),
            "abstain": list(bucket.get("abstain") or []),
            "reasons": dict(bucket.get("reasons") or {}),
        }
    return {
        "id": carry_id,
        "vendor": c.get("vendor"),
        "text": c.get("text", ""),
        "addendums": addendums,
        "subcomments": subcomments,
        "votes": {
            "up": list(votes.get("up") or []),
            "down": list(votes.get("down") or []),
            "abstain": list(votes.get("abstain") or []),
        },
        "removed": bool(c.get("removed")) or len(votes.get("down") or []) > 0,
        "created_round": int(c.get("created_round") or 1),
        "votes_by_round": vote_rounds_out,
        "carried_from_topic": carry_topic,
        "carried_from_comment_id": c.get("id"),
        "carried": True,
    }


def get_prior_topic_top_comments(
    threads: Dict[str, List[Dict[str, Any]]],
    topic: str,
    *,
    max_per_topic: int = 3,
) -> List[Dict[str, Any]]:
    """Return top surviving comments from topics that come before `topic`."""
    out: List[Dict[str, Any]] = []
    try:
        topic_index = AGENTIC_TOPIC_KEYS.index(topic)
    except ValueError:
        return out
    for prev_topic in AGENTIC_TOPIC_KEYS[:topic_index]:
        candidates = []
        for c in (threads.get(prev_topic) or []):
            if _is_comment_removed(c):
                continue
            candidates.append(c)
        candidates.sort(key=_comment_score, reverse=True)
        for c in candidates[:max_per_topic]:
            out.append(_clone_comment_for_carryover(
                c,
                carry_topic=prev_topic,
                carry_id=f"{prev_topic}:{c.get('id') or str(uuid.uuid4())[:8]}",
            ))
    return out


def seed_thread_with_prior_topic_comments(
    thread: List[Dict[str, Any]],
    prior_comments: List[Dict[str, Any]],
) -> None:
    """Inject prior-topic top comments once so current topic can vote/comment/add to them."""
    existing = {c.get("id") for c in thread if c.get("id")}
    for c in prior_comments:
        cid = c.get("id")
        if not cid or cid in existing:
            continue
        thread.append(c)
        existing.add(cid)


def merge_carryover_updates_and_strip(
    topic_thread: List[Dict[str, Any]],
    threads: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Persist carry-over comment interactions back to their source topic, then remove
    carry-over clones from the current topic thread so users only see local comments.
    """

    def _clone_addendums(addendums: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cloned: List[Dict[str, Any]] = []
        for a in addendums or []:
            na = dict(a)
            na["up"] = list(na.get("up") or [])
            na["down"] = list(na.get("down") or [])
            cloned.append(na)
        return cloned

    def _clone_subcomments(subcomments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [dict(s) for s in (subcomments or [])]

    visible_thread: List[Dict[str, Any]] = []
    for comment in topic_thread:
        if not comment.get("carried"):
            visible_thread.append(comment)
            continue

        source_topic = comment.get("carried_from_topic")
        source_comment_id = comment.get("carried_from_comment_id")
        if not source_topic or not source_comment_id:
            continue

        source_thread = threads.get(source_topic) or []
        source = next((c for c in source_thread if c.get("id") == source_comment_id), None)
        if source is None:
            continue

        source["addendums"] = _clone_addendums(comment.get("addendums") or [])
        source["subcomments"] = _clone_subcomments(comment.get("subcomments") or [])
        votes = comment.get("votes") or {}
        source["votes"] = {
            "up": list(votes.get("up") or []),
            "down": list(votes.get("down") or []),
            "abstain": list(votes.get("abstain") or []),
        }
        vote_rounds = comment.get("votes_by_round") or {}
        source["votes_by_round"] = {}
        for round_key, bucket in vote_rounds.items():
            if not isinstance(bucket, dict):
                continue
            source["votes_by_round"][str(round_key)] = {
                "up": list(bucket.get("up") or []),
                "down": list(bucket.get("down") or []),
                "abstain": list(bucket.get("abstain") or []),
                "reasons": dict(bucket.get("reasons") or {}),
            }
        source["created_round"] = int(comment.get("created_round") or source.get("created_round") or 1)
        source["removed"] = bool(comment.get("removed")) or len(source["votes"]["down"]) > 0

    return visible_thread


def format_prior_topic_comments_for_prompt(prior_comments: List[Dict[str, Any]]) -> str:
    """Compact formatter for prior-topic carry-over comments."""
    if not prior_comments:
        return "(No prior-topic carry-over comments.)"
    lines: List[str] = []
    for i, c in enumerate(prior_comments):
        label = _topic_label(c.get("carried_from_topic", "unknown"))
        lines.append(f"- [{label}] id={c.get('id', f'pc{i}')} by {c.get('vendor', '?')}: {c.get('text', '')}")
        for a in (c.get("addendums") or []):
            lines.append(
                f"  Addendum by {a.get('vendor', '?')} (up={len(a.get('up') or [])}, down={len(a.get('down') or [])}): {a.get('text', '')}"
            )
        for s in (c.get("subcomments") or []):
            lines.append(f"  Reply by {s.get('vendor', '?')}: {s.get('text', '')}")
    return "\n".join(lines)


def _format_thread_for_prompt(thread: List[Dict], topic: str, feedback_vendors: Optional[List[str]] = None) -> str:
    """Format current thread for the prompt: effective comment text (with incorporated addendums), new addendums, open vs finalized."""
    if not thread:
        return "(No comments yet.)"
    vendor_set = set(feedback_vendors or [])
    lines = []
    for i, c in enumerate(thread):
        cid = c.get("id", f"c{i}")
        is_removed = _is_comment_removed(c)
        acted = _comment_acted_vendors(c)
        is_open = (not is_removed) and (not vendor_set or (acted < vendor_set))
        status = "REMOVED" if is_removed else ("OPEN" if is_open else "FINALIZED")
        lines.append(f"--- Comment {i+1} [id={cid}] [{status}] by {c.get('vendor', '?')} ---")
        if c.get("carried"):
            lines.append(
                f"[Carried from previous topic: {c.get('carried_from_topic', '?')}, original_comment_id={c.get('carried_from_comment_id', '?')}]"
            )
        # Effective text: comment + addendums that have positive net votes (incorporated)
        effective_parts = [c.get("text", "")]
        new_addendum_lines = []
        for ai, a in enumerate(c.get("addendums", [])):
            _ensure_addendum_id(a, i, ai)
            aup = a.get("up") or []
            adown = a.get("down") or []
            if len(aup) > len(adown):
                effective_parts.append(f"  [Incorporated addendum] {a.get('text', '')}")
            else:
                new_addendum_lines.append(f"  New addendum [id={a.get('id')}] by {a.get('vendor', '?')} (up={len(aup)}, down={len(adown)}): {a.get('text', '')}")
        lines.append("\n".join(effective_parts))
        if new_addendum_lines:
            lines.append("  New addendums (you must upvote or downvote each):")
            lines.extend(new_addendum_lines)
        for s in c.get("subcomments", []):
            lines.append(f"  Reply by {s.get('vendor', '?')}: {s.get('text', '')}")
        up = c.get("votes", {}).get("up", [])
        down = c.get("votes", {}).get("down", [])
        lines.append(f"  Comment votes: up={len(up)} {up}, down={len(down)} {down}")
        abstain = c.get("votes", {}).get("abstain", [])
        if abstain:
            lines.append(f"  Comment abstain={len(abstain)} {abstain}")
        lines.append("")
    return "\n".join(lines).strip()


def _agentic_feedback_prompt_first_agent(topic: str, context: str, topic_label: str) -> tuple:
    """System and user prompt for the first agent (no existing comments)."""
    system = (
        f"You are a feedback agent for the '{topic_label}' dimension of a cover letter. "
        "You see the draft letter(s) and the relevant context.\n\n"
        "RULES:\n"
        "- Do NOT pick a 'best' draft or declare any single proposal the winner.\n"
        "- Discuss specific strengths and weaknesses of each proposal.\n"
        "- When praising or criticizing a passage, you MUST quote the exact words from the draft "
        "(use quotation marks) so your comment is fully understandable on its own, even without "
        "the original drafts.\n"
        "- Suggest concrete changes where appropriate.\n\n"
        "If you have substantive feedback (issues or suggestions for the draft), write it in a single comment. "
        "If you have nothing to add, output exactly: NO COMMENT (or SKIP). "
        "Do not add anything after NO COMMENT or SKIP. "
        "Your response must be either: (1) your feedback text, or (2) exactly 'NO COMMENT' or 'SKIP'."
    )
    prompt = (
        context + "\n\n"
        "Discuss the strengths and weaknesses of each draft for this dimension. "
        "Quote exact phrases when praising or criticizing. Do NOT pick a best draft. "
        "Reply with your comment, or with NO COMMENT (or SKIP) if you have nothing to add."
    )
    return system, prompt


def _agentic_feedback_prompt_subsequent(
    topic: str, context: str, thread_str: str, topic_label: str, prior_topic_comments_str: str = ""
) -> tuple:
    """System and user prompt for agents that see existing comments."""
    system = (
        f"You are a feedback agent for the '{topic_label}' dimension. "
        "You see the draft, context, and the current thread. Comments marked [OPEN] require your action; [FINALIZED] comments are closed (all bots have already acted); [REMOVED] comments are visible for audit but must never be used downstream.\n\n"
        "RULES:\n"
        "- Do NOT pick a 'best' draft or declare any single proposal the winner.\n"
        "- When praising or criticizing a passage, you MUST quote the exact words from the draft "
        "(use quotation marks) so your comment is fully understandable on its own.\n"
        "- Suggest concrete changes where appropriate.\n\n"
        "Order of actions:\n"
        "1) Optionally add one new top-level comment (only if you have an original, substantive point not already in the thread).\n"
        "2) For each NEW addendum listed in the thread (those under 'New addendums (you must upvote or downvote each)'): you must either upvote or downvote it by addendum_id. No new addendum text when voting existing addendums.\n"
        "3) For each OPEN top-level comment: choose exactly one of: upvote the comment, downvote the comment, abstain, add a subcomment, or add one addendum. Do not interact with FINALIZED or REMOVED comments.\n\n"
        "Hard rule: if you downvote a top-level comment, that comment is removed forever from downstream rewrite inputs.\n\n"
        "Abstain usage: use abstain only when the comment is not relevant to this topic.\n\n"
        "Consistency rule: when prior-topic comments contradict evidence in this topic, downvote the inconsistent comment so it is removed from downstream use.\n\n"
        "Anti-repetition: Do not add subcomments that only say 'I agree'. Do not add a top-level comment or addendum that repeats what is already said. If you have nothing original to add, only vote (upvote/downvote) and leave new_comment null and do not add addendum text. Adding an addendum invalidates the comment's existing votes (one more reason not to add one lightly). Only addendums with positive net votes are used in the draft revision.\n\n"
        "Subcomments are for discussion (e.g. clarifying before an addendum); only add when non-redundant. New addendum = concrete, actionable revision suggestion (e.g. 'Add a sentence about X'); not meta-commentary.\n\n"
        "JSON response: subcomments (list of {comment_id, text}), votes (list of {comment_id, action, reason?: string, addendum_id?: string, addendum?: string}), new_comment (string or null). "
        "action is one of: upvote, downvote, abstain (comment-only), upvote_addendum (with addendum_id to upvote existing, or addendum text to create new). "
        "Use comment 'id' for comment_id; addendum 'id' for addendum_id. For each new addendum you must include a vote with addendum_id and action upvote or downvote. For each open comment you must include one vote or one subcomment or one addendum. "
        "When you vote on a top-level comment, include reason as a short phrase (max ~12 words) explaining why."
    )
    prior_section = ""
    if prior_topic_comments_str:
        prior_section = (
            "========== Prior topics: top surviving comments ==========\n"
            + prior_topic_comments_str + "\n\n"
        )
    prompt = (
        context + "\n\n"
        + prior_section
        + "========== Current thread ==========\n" + thread_str + "\n\n"
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
    feedback_vendors: Optional[List[str]] = None,
    prior_topic_comments: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call one feedback agent for one topic. Returns parsed actions: subcomments, votes, new_comment.
    For first agent (empty thread), we do a simple text response; for subsequent, we ask for JSON.
    feedback_vendors is used to mark open vs finalized comments (finalized = all bots have acted).
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
    thread_str = _format_thread_for_prompt(thread, topic, feedback_vendors)
    system, prompt = _agentic_feedback_prompt_subsequent(
        topic, context, thread_str, topic_label, prior_topic_comments_str=(prior_topic_comments or "")
    )
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
    round_num: Optional[int] = None,
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
            if _is_comment_removed(thread[idx]):
                continue
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
        if _is_comment_removed(thread[idx]):
            continue
        action = (v.get("action") or "").lower()
        if action == "abstain":
            if _set_comment_vote_action(
                thread[idx],
                vendor,
                "abstain",
                round_num=round_num,
                reason=v.get("reason") or v.get("rationale") or "",
            ):
                changed = True
            continue
        if "up" in action or action == "upvote":
            if _set_comment_vote_action(
                thread[idx],
                vendor,
                "up",
                round_num=round_num,
                reason=v.get("reason") or v.get("rationale") or "",
            ):
                changed = True
            addendum_text = (v.get("addendum") or v.get("text") or "").strip()
            addendum_id = v.get("addendum_id") or v.get("addendumId")
            if addendum_id and not addendum_text:
                # Upvote existing addendum; if it becomes positive net, invalidate parent comment votes
                loc = addendum_by_id.get(addendum_id)
                if loc is not None:
                    ci, ai = loc
                    addendum = thread[ci]["addendums"][ai]
                    if "up" not in addendum:
                        addendum["up"] = []
                    if "down" not in addendum:
                        addendum["down"] = []
                    if vendor not in addendum["up"]:
                        addendum["up"].append(vendor)
                        changed = True
                    if len(addendum["up"]) > len(addendum["down"]):
                        # Addendum is now positive; invalidate existing votes on the top-level comment
                        if thread[ci].get("votes"):
                            thread[ci]["votes"] = {"up": [], "down": [], "abstain": []}
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
                    "down": [],
                }
                thread[idx]["addendums"].append(new_a)
                addendum_by_id[new_a["id"]] = (idx, len(thread[idx]["addendums"]) - 1)
                changed = True
                # New addendum is positive (author upvote); invalidate parent comment votes
                if thread[idx].get("votes"):
                    thread[idx]["votes"] = {"up": [], "down": [], "abstain": []}
                    changed = True
        elif "down" in action or action == "downvote":
            addendum_id = v.get("addendum_id") or v.get("addendumId")
            if addendum_id:
                loc = addendum_by_id.get(addendum_id)
                if loc is not None:
                    ci, ai = loc
                    addendum = thread[ci]["addendums"][ai]
                    if "down" not in addendum:
                        addendum["down"] = []
                    if vendor not in addendum["down"]:
                        addendum["down"].append(vendor)
                        changed = True
            else:
                if _set_comment_vote_action(
                    thread[idx],
                    vendor,
                    "down",
                    round_num=round_num,
                    reason=v.get("reason") or v.get("rationale") or "",
                ):
                    changed = True
                # Any downvote permanently removes the comment from downstream use.
                if not thread[idx].get("removed"):
                    thread[idx]["removed"] = True
                    changed = True
    new_comment = response.get("new_comment")
    if new_comment and isinstance(new_comment, str) and new_comment.strip():
        thread.append({
            "id": str(uuid.uuid4())[:8],
            "vendor": vendor,
            "text": new_comment.strip(),
            "addendums": [],
            "votes": {"up": [], "down": [], "abstain": []},
            "votes_by_round": {},
            "subcomments": [],
            "removed": False,
            "created_round": int(round_num or 1),
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


def _format_all_threads_for_voting(threads: Dict[str, List[Dict]]) -> str:
    """Format all discussion threads into a single string for the voting prompt."""
    parts = []
    for topic in AGENTIC_TOPIC_KEYS:
        thread = threads.get(topic, [])
        if not thread:
            continue
        label = _topic_label(topic)
        parts.append(f"===== {label} Discussion =====")
        for i, c in enumerate(thread):
            parts.append(f"[{c.get('vendor', '?')}]: {c.get('text', '')}")
            for a in c.get("addendums", []):
                aup = len(a.get("up") or [])
                adown = len(a.get("down") or [])
                parts.append(f"  Addendum by {a.get('vendor', '?')} (up={aup}, down={adown}): {a.get('text', '')}")
            for s in c.get("subcomments", []):
                parts.append(f"  Reply by {s.get('vendor', '?')}: {s.get('text', '')}")
        parts.append("")
    return "\n".join(parts).strip()


def _format_draft_letters_for_voting(draft_letters: Dict[str, str]) -> str:
    """Format all draft letters for the voting prompt."""
    parts = []
    for vendor, letter in draft_letters.items():
        parts.append(f"===== Draft by {vendor} =====\n{letter}\n")
    return "\n".join(parts).strip()


def _call_voting_agent(
    vendor: str,
    draft_letters: Dict[str, str],
    threads: Dict[str, List[Dict]],
    client=None,
) -> List[str]:
    """
    Call one agent to vote for their top 3 favorite drafts.
    Returns list of up to 3 vendor names (ordered by preference).
    """
    if client is None:
        client = get_client(ModelVendor(vendor))
    draft_vendors = list(draft_letters.keys())
    drafts_str = _format_draft_letters_for_voting(draft_letters)
    discussion_str = _format_all_threads_for_voting(threads)

    system = (
        "You are a voting agent. You have read multiple draft cover letters and a discussion "
        "of their strengths and weaknesses. Now you must vote for your top 3 favorite drafts.\n\n"
        "Consider that the chosen draft will be revised based on the discussion comments, "
        "so a draft with fixable weaknesses may still be a strong candidate.\n\n"
        "Respond with ONLY a JSON array of up to 3 vendor names, ordered from most to least preferred. "
        "Example: [\"openai\", \"anthropic\", \"gemini\"]\n"
        "No explanation, no markdown, just the JSON array."
    )
    prompt = (
        drafts_str + "\n\n"
        "===== Agent Discussion =====\n" + discussion_str + "\n\n"
        f"The available draft vendors are: {json.dumps(draft_vendors)}\n\n"
        "Vote for your top 3 favorites (JSON array of vendor names, most preferred first)."
    )
    raw = client.call(ModelSize.TINY, system, [prompt])
    raw = (raw or "").strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        votes = json.loads(raw)
        if isinstance(votes, list):
            return [v for v in votes if isinstance(v, str) and v in draft_letters][:3]
    except json.JSONDecodeError:
        pass
    _log(f"AGENTIC voting: {vendor} returned unparseable response: {raw[:200]}")
    return []


def run_agentic_voting(
    session,
    voting_vendors: List[str],
) -> Dict[str, Any]:
    """
    After discussion, each vendor reads all drafts + discussion and votes for top 3.
    Stores vote tallies in state['draft_votes'].
    """
    _require_session(session)
    state = get_agentic_state(session)
    if not state:
        raise ValueError("Agentic state missing")
    if state.get("status") not in (STATUS_FEEDBACK_DONE,) and state.get("feedback_ongoing") is not False:
        raise ValueError("Voting requires feedback to be complete")
    if state.get("status") != STATUS_FEEDBACK_DONE:
        state["status"] = STATUS_FEEDBACK_DONE

    draft_letters = state.get("draft_letters") or {}
    threads = state.get("threads") or _empty_threads()

    if not draft_letters or len(draft_letters) < 2:
        _log("AGENTIC voting: fewer than 2 drafts, skipping vote (all get 1)")
        state["draft_votes"] = {v: 1 for v in draft_letters}
        save_agentic_state(session, state)
        return state

    vote_tallies: Dict[str, int] = {v: 0 for v in draft_letters}
    total_cost = 0.0
    user_id = _user_id(session)

    def _one_vote(voter: str) -> Tuple[str, List[str], float]:
        client = get_client(ModelVendor(voter))
        top3 = _call_voting_agent(voter, draft_letters, threads, client=client)
        cost = getattr(client, "total_cost", 0.0) or 0.0
        return (voter, top3, cost)

    with ThreadPoolExecutor(max_workers=min(len(voting_vendors), 4)) as executor:
        futures = {executor.submit(_one_vote, v): v for v in voting_vendors}
        for fut in as_completed(futures):
            voter = futures[fut]
            try:
                voter, top3, cost = fut.result()
                _log(f"AGENTIC voting: {voter} voted for {top3}")
                for ranked_vendor in top3:
                    vote_tallies[ranked_vendor] = vote_tallies.get(ranked_vendor, 0) + 1
                total_cost += cost
                if cost > 0:
                    track_api_cost(user_id, "vote", voter, cost)
            except Exception as e:
                _log(f"AGENTIC voting error for {voter}: {e}")

    state["draft_votes"] = vote_tallies
    state["cost"] = state.get("cost", 0) + total_cost
    save_agentic_state(session, state)
    _log(f"AGENTIC voting complete: {vote_tallies}")
    return state


def _sample_drafts_for_vendor(
    draft_letters: Dict[str, str],
    draft_votes: Dict[str, int],
    target_vendor: str,
    num_agents: int,
    n: int = 3,
) -> List[str]:
    """
    Sample n draft vendors proportional to votes, with bias: target_vendor gets
    +num_agents votes (as if every agent cast one extra vote for it).
    Returns up to n unique vendor names (no duplicates).
    """
    vendors = list(draft_letters.keys())
    if len(vendors) <= n:
        return vendors

    weights = []
    for v in vendors:
        w = draft_votes.get(v, 0)
        if v == target_vendor:
            w += num_agents
        weights.append(max(w, 1))

    # Weighted sample without replacement: preserve vote bias while ensuring
    # we never include the same draft multiple times in reference examples.
    sample_count = min(n, len(vendors))
    chosen: List[str] = []
    pool = list(zip(vendors, weights))
    for _ in range(sample_count):
        pool_vendors = [v for v, _ in pool]
        pool_weights = [w for _, w in pool]
        selected = random.choices(pool_vendors, weights=pool_weights, k=1)[0]
        chosen.append(selected)
        pool = [(v, w) for v, w in pool if v != selected]
    return chosen


def run_agentic_draft(
    session,
    draft_vendor: str,
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    style_instructions: str = "",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
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
            company_report = company_report or ""

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
    state["draft_letters"] = {draft_vendor: draft_letter}
    state["draft_vendor"] = draft_vendor
    state["round"] = 0
    state["status"] = STATUS_FEEDBACK
    state["threads"] = _empty_threads()
    state["feedback_ongoing"] = False
    state["feedback_suspended"] = False
    state.pop("topic_cursors", None)
    state.pop("feedback_vendor_order", None)
    state.pop("draft_votes", None)
    state["cost"] = state.get("cost", 0) + cost
    state["top_docs"] = top_docs
    state["company_report"] = company_report
    state["job_text"] = job_text
    state["cv_text"] = cv_text
    state["metadata"] = metadata
    state["style_instructions"] = style_instructions
    state["max_rounds"] = max_rounds
    save_agentic_state(session, state)
    if cost > 0:
        track_api_cost(_user_id(session), "draft", draft_vendor, cost)
    return state


def run_agentic_draft_multi(
    session,
    draft_vendors: List[str],
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    style_instructions: str = "",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> Dict[str, Any]:
    """
    Generate one draft letter per selected vendor and store in state as draft_letters.
    Uses session common data; runs background once (first vendor) if company_report/top_docs not provided.
    """
    _require_session(session)
    if not draft_vendors:
        raise ValueError("draft_vendors must be non-empty")
    job_text = session.get("job_text", "")
    cv_text = session.get("cv_text", "")
    metadata = session.get("metadata", {})
    top_docs = list(top_docs_override) if top_docs_override else []
    company_report = company_report_override or ""
    first_vendor = draft_vendors[0]

    if not company_report or not top_docs:
        vendor_enum = ModelVendor(first_vendor)
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
            company_report = company_report or ""
        # #region agent log
        try:
            import json
            with open("/home/fdondi/Documents/#GitHub/letter-writer/.cursor/debug-5b1b21.log", "a") as _f:
                _f.write(json.dumps({"sessionId": "5b1b21", "hypothesisId": "H4", "location": "agentic_service.py:run_agentic_draft_multi", "message": "after company_research", "data": {"company_report_is_none": company_report is None, "company_report_type": type(company_report).__name__}, "timestamp": __import__("time").time() * 1000}) + "\n")
        except Exception:
            pass
        # #endregion

    if not style_instructions:
        style_instructions = session.get("style_instructions", "") or get_style_instructions()

    draft_letters_dict: Dict[str, str] = {}
    vendor_errors: Dict[str, str] = {}
    total_cost = 0.0

    def _one_draft(vendor: str) -> Tuple[str, str, float]:
        trace_dir = Path("trace", "agentic.draft")
        trace_dir.mkdir(parents=True, exist_ok=True)
        additional_user_info = get_metadata_field(metadata, ModelVendor(vendor), "additional_user_info", "")
        ai_client = get_client(ModelVendor(vendor))
        letter = generate_letter(
            cv_text, top_docs, company_report, job_text, ai_client, trace_dir,
            style_instructions, additional_user_info,
        )
        cost = getattr(ai_client, "total_cost", 0.0) or 0.0
        return (vendor, letter, cost)

    with ThreadPoolExecutor(max_workers=min(len(draft_vendors), 4)) as executor:
        futures = {executor.submit(_one_draft, v): v for v in draft_vendors}
        user_id = _user_id(session)
        for fut in as_completed(futures):
            vendor = futures[fut]
            try:
                vendor, letter, cost = fut.result()
                draft_letters_dict[vendor] = letter
                total_cost += cost
                if cost > 0:
                    track_api_cost(user_id, "draft", vendor, cost)
            except Exception as e:
                err_msg = str(e)
                _log(f"AGENTIC draft error for vendor {vendor}: {e}")
                vendor_errors[vendor] = err_msg

    if not draft_letters_dict:
        # All vendors failed: raise so the client gets an error response
        if vendor_errors:
            combined = "; ".join(f"{v}: {msg}" for v, msg in vendor_errors.items())
            raise RuntimeError(combined)
        raise ValueError("No draft letters produced")

    # Use first successful vendor as primary
    first_success = next(v for v in draft_vendors if v in draft_letters_dict)
    state = _ensure_agentic_state(session)
    state["draft_letters"] = draft_letters_dict
    state["draft_letter"] = draft_letters_dict.get(first_success) or ""
    state["draft_vendor"] = first_success
    if vendor_errors:
        state["vendor_errors"] = vendor_errors
    state["round"] = 0
    state["status"] = STATUS_FEEDBACK
    state["threads"] = _empty_threads()
    state["feedback_ongoing"] = False
    state["feedback_suspended"] = False
    state.pop("topic_cursors", None)
    state.pop("feedback_vendor_order", None)
    state.pop("draft_votes", None)
    state["cost"] = state.get("cost", 0) + total_cost
    state["top_docs"] = top_docs
    state["company_report"] = company_report
    state["job_text"] = job_text
    state["cv_text"] = cv_text
    state["metadata"] = metadata
    state["style_instructions"] = style_instructions
    state["max_rounds"] = max_rounds
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

    draft_letters_multi = state.get("draft_letters") or {}
    for topic in AGENTIC_TOPIC_KEYS:
        context = get_agentic_topic_context(
            topic, draft_letter, cv_text, company_report, job_text, top_docs,
            style_instructions, additional_user_info,
            draft_letters=draft_letters_multi if len(draft_letters_multi) > 0 else None,
        )
        thread = list(threads.get(topic, []))
        prior_comments = get_prior_topic_top_comments(threads, topic)
        seed_thread_with_prior_topic_comments(thread, prior_comments)
        prior_comments_text = format_prior_topic_comments_for_prompt(prior_comments)
        order = list(feedback_vendors)
        random.shuffle(order)
        for vendor in order:
            try:
                _log(f"AGENTIC feedback round {round_num}: topic={topic} vendor={vendor}")
                response = _call_agentic_feedback_agent(
                    vendor,
                    topic,
                    context,
                    thread,
                    trace_dir,
                    prior_topic_comments=prior_comments_text,
                )
                if _apply_agent_response(thread, vendor, response, round_num=round_num):
                    any_change = True
            except Exception as e:
                _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
        threads[topic] = merge_carryover_updates_and_strip(thread, threads)
        state["threads"] = threads
        save_agentic_state(session, state)

    state["threads"] = threads
    positive_count = _count_positive_comments(threads)
    max_rounds = _get_max_rounds(state)
    if not any_change or round_num >= max_rounds or positive_count > MAX_POSITIVE_COMMENTS:
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
    state["feedback_suspended"] = False
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


def add_agentic_round_to_state(
    state: Dict[str, Any], all_topics: bool = True, topic: Optional[str] = None
) -> None:
    """Mutate state: add one round for all topics (increment max_rounds) or for one topic (decrement its round)."""
    if all_topics:
        state["max_rounds"] = (state.get("max_rounds") or DEFAULT_MAX_ROUNDS) + 1
        return
    if topic and topic in AGENTIC_TOPIC_KEYS:
        if "topic_cursors" not in state or state["topic_cursors"] is None:
            state["topic_cursors"] = {}
        cursors = state["topic_cursors"]
        cur = cursors.get(topic) or {}
        cur = dict(cur)
        cur["round"] = max(1, (cur.get("round") or 1) - 1)
        cursors[topic] = cur


def add_agentic_round(
    session, all_topics: bool = True, topic: Optional[str] = None
) -> Dict[str, Any]:
    """Add one round for all topics (increment max_rounds) or one topic (decrement its round). Persist and return state."""
    _require_session(session)
    state = get_agentic_state(session)
    if not state or state.get("status") not in (STATUS_FEEDBACK, STATUS_FEEDBACK_DONE):
        raise ValueError("Agentic state missing or not in feedback phase")
    add_agentic_round_to_state(state, all_topics=all_topics, topic=topic)
    save_agentic_state(session, state)
    return state


def _run_one_topic_agent(
    topic: str,
    vendor: str,
    context: str,
    thread_copy: List[Dict],
    trace_dir: Path,
    prior_topic_comments_text: str = "",
    round_num: Optional[int] = None,
) -> Tuple[str, List[Dict]]:
    """Run one feedback agent for one topic (used in thread pool). Writes only to thread_copy; returns (topic, thread)."""
    try:
        _log(f"AGENTIC topic={topic} vendor={vendor}")
        response = _call_agentic_feedback_agent(
            vendor, topic, context, thread_copy, trace_dir, prior_topic_comments=prior_topic_comments_text
        )
        _apply_agent_response(thread_copy, vendor, response, round_num=round_num)
    except Exception as e:
        _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
    return (topic, thread_copy)


def _run_one_topic_sequential(
    topic: str,
    context: str,
    thread: List[Dict],
    vendor_order: List[str],
    trace_dir: Path,
    prior_topic_comments_text: str = "",
    should_abort: Optional[Callable[[], bool]] = None,
    round_num: Optional[int] = None,
) -> Tuple[str, List[Dict], bool]:
    """Run all vendors for one topic sequentially so each agent sees previous addendums. Returns (topic, updated_thread)."""
    for vendor in vendor_order:
        if should_abort is not None and should_abort():
            _log(f"AGENTIC topic={topic}: abort before vendor={vendor} due to stale polling heartbeat")
            return (topic, thread, False)
        try:
            _log(f"AGENTIC topic={topic} vendor={vendor} (sequential)")
            response = _call_agentic_feedback_agent(
                vendor,
                topic,
                context,
                thread,
                trace_dir,
                feedback_vendors=vendor_order,
                prior_topic_comments=prior_topic_comments_text,
            )
            _apply_agent_response(thread, vendor, response, round_num=round_num)
        except Exception as e:
            _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
    return (topic, thread, True)


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

    draft_letters_multi = state.get("draft_letters") or {}
    # Build one work item per topic: run all vendors for that topic sequentially so each sees prior addendums
    work = []
    for topic in AGENTIC_TOPIC_KEYS:
        cur = topic_cursors[topic]
        order = cur.get("vendor_order") or []
        if not order:
            continue
        round_num = int(cur.get("round") or 1)
        prior_comments = get_prior_topic_top_comments(threads, topic)
        prior_comments_text = format_prior_topic_comments_for_prompt(prior_comments)
        context = get_agentic_topic_context(
            topic, draft_letter, cv_text, company_report, job_text, top_docs,
            style_instructions, additional_user_info,
            draft_letters=draft_letters_multi if len(draft_letters_multi) > 0 else None,
        )
        # Copy thread so each topic's worker has its own list/dicts (no shared refs across parallel topics)
        thread_copy = []
        for c in (threads.get(topic) or []):
            nc = dict(c)
            nc["addendums"] = []
            for a in (nc.get("addendums") or []):
                na = dict(a)
                na["up"] = list(na.get("up") or [])
                na["down"] = list(na.get("down") or [])
                nc["addendums"].append(na)
            nc["subcomments"] = list(nc.get("subcomments") or [])
            v = nc.get("votes") or {}
            nc["votes"] = {
                "up": list(v.get("up", [])),
                "down": list(v.get("down", [])),
                "abstain": list(v.get("abstain", [])),
            }
            vbr = nc.get("votes_by_round") or {}
            nc["votes_by_round"] = {}
            for rk, bucket in vbr.items():
                if not isinstance(bucket, dict):
                    continue
                nc["votes_by_round"][str(rk)] = {
                    "up": list(bucket.get("up") or []),
                    "down": list(bucket.get("down") or []),
                    "abstain": list(bucket.get("abstain") or []),
                    "reasons": dict(bucket.get("reasons") or {}),
                }
            thread_copy.append(nc)
        seed_thread_with_prior_topic_comments(thread_copy, prior_comments)
        work.append((topic, context, thread_copy, order, trace_dir, prior_comments_text, round_num))

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
        max_rounds = _get_max_rounds(state)
        all_topics_finished = all(r > max_rounds for r in rounds.values())
        if min_round <= MIN_ROUNDS_BEFORE_DONE:
            _log(f"AGENTIC no work this poll, min_round={min_round} — not stopping (need all topics >{max_rounds} or positive cap)")
        elif all_topics_finished or positive_count > MAX_POSITIVE_COMMENTS:
            state["feedback_ongoing"] = False
            state["status"] = STATUS_FEEDBACK_DONE
            _log(f"AGENTIC feedback done (all topics signalled): rounds={rounds} positive_count={positive_count}")
        save_agentic_state(session, state)
        return (state, state.get("feedback_ongoing", False))

    # Run each topic's full vendor sequence in parallel (within a topic, vendors run sequentially and see prior addendums)
    with ThreadPoolExecutor(max_workers=len(AGENTIC_TOPIC_KEYS)) as executor:
        futures = {
            executor.submit(_run_one_topic_sequential, t, c, th, order, trace_dir, prior_text, None, round_num): t
            for (t, c, th, order, trace_dir, prior_text, round_num) in work
        }
        for fut in as_completed(futures):
            topic, updated_thread, _ = fut.result()
            threads[topic] = merge_carryover_updates_and_strip(updated_thread, threads)
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
    max_rounds = _get_max_rounds(state)
    _log(f"AGENTIC poll step: work_count={len(work)} min_round={min_round} rounds={rounds_per_topic}")

    # Ongoing becomes false only when every topic thread has signalled done (round > max_rounds for all), or positive cap.
    # We never set done just because this poll ran — only when the state explicitly has all topics finished.
    all_topics_finished = all(r > max_rounds for r in rounds_per_topic.values())
    if min_round <= MIN_ROUNDS_BEFORE_DONE:
        _log(f"AGENTIC not done: min_round={min_round} (need all topics >{max_rounds} or positive cap)")
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
    Collect all positive-vote comments and addendums, then produce one final letter per vendor.
    For each vendor, 3 draft examples are sampled proportional to votes (with same-vendor bias)
    and included in the rewrite prompt so the rewriter can draw from the best drafts.
    Allow when status is feedback_done OR when feedback has stopped (feedback_ongoing false).
    If threads_override is provided, use it instead of state threads (e.g. user-edited).
    """
    _require_session(session)
    state = get_agentic_state(session)
    if not state:
        raise ValueError("Agentic state missing")
    if state.get("status") != STATUS_FEEDBACK_DONE and state.get("feedback_ongoing") is not False:
        raise ValueError("Agentic state missing or not in feedback_done phase")
    if state.get("status") != STATUS_FEEDBACK_DONE:
        state["status"] = STATUS_FEEDBACK_DONE
    draft_letters = state.get("draft_letters") or {}
    if not draft_letters:
        draft_letters = {state.get("draft_vendor") or "": state.get("draft_letter") or ""}
        if not any(draft_letters.values()):
            draft_letters = {}
    draft_letter = state.get("draft_letter") or ""
    draft_vendor = state.get("draft_vendor") or (list(draft_letters.keys())[0] if draft_letters else "")
    threads = threads_override if threads_override is not None else (state.get("threads") or _empty_threads())
    if threads_override is not None:
        state["threads"] = threads

    draft_votes = state.get("draft_votes") or {}
    feedback_vendors = state.get("feedback_vendor_order") or list(draft_letters.keys())
    num_agents = len(feedback_vendors)

    parts = []
    for topic in AGENTIC_TOPIC_KEYS:
        thread = threads.get(topic, [])
        for c in thread:
            up = len(c.get("votes", {}).get("up", []))
            down = len(c.get("votes", {}).get("down", []))
            if _is_comment_removed(c):
                continue
            if up == 0:
                continue
            label = _topic_label(topic)
            parts.append(f"[{label}] {c.get('text', '')}")
            for a in c.get("addendums", []):
                aup = a.get("up") or []
                adown = a.get("down") or []
                if len(aup) <= len(adown):
                    continue
                parts.append(f"  Addendum: {a.get('text', '')}")
    combined = "\n\n".join(parts) if parts else ""

    trace_dir = Path("trace", "agentic.refine")
    trace_dir.mkdir(parents=True, exist_ok=True)
    final_letters_dict: Dict[str, str] = {}
    total_cost = 0.0

    if not draft_letters:
        state["final_letter"] = draft_letter
        state["final_letters"] = {}
        state["status"] = STATUS_DONE
        save_agentic_state(session, state)
        return state

    user_id = _user_id(session)
    refine_samples: Dict[str, List[str]] = {}
    for vendor, d_letter in draft_letters.items():
        if not d_letter.strip():
            final_letters_dict[vendor] = d_letter
            continue
        if not combined.strip():
            final_letters_dict[vendor] = d_letter
            continue

        if draft_votes and len(draft_letters) > 1:
            sampled_vendors = _sample_drafts_for_vendor(
                draft_letters, draft_votes, vendor, num_agents, n=3
            )
            refine_samples[vendor] = sampled_vendors
            _log(f"AGENTIC refine {vendor}: sampled drafts from {sampled_vendors} (votes={draft_votes})")
            reference_block = "\n\n".join(
                f"===== Reference draft by {sv} =====\n{draft_letters[sv]}"
                for sv in sampled_vendors if draft_letters.get(sv)
            )
            instruction_fb = (
                f"===== Reference drafts (sampled by vote, consider drawing from their strengths) =====\n"
                f"{reference_block}\n\n"
                f"===== Discussion feedback =====\n{combined}"
            )
        else:
            instruction_fb = combined

        ai_client = get_client(ModelVendor(vendor))
        final_letter = rewrite_letter(
            d_letter,
            instruction_fb, "NO COMMENT", "NO COMMENT",
            "NO COMMENT", "NO COMMENT", "NO COMMENT",
            ai_client, trace_dir,
        )
        final_letters_dict[vendor] = final_letter
        cost_inc = getattr(ai_client, "total_cost", 0.0) or 0.0
        total_cost += cost_inc
        if cost_inc > 0:
            track_api_cost(user_id, "refine", vendor, cost_inc)

    first_v = list(final_letters_dict.keys())[0] if final_letters_dict else draft_vendor
    state["final_letters"] = final_letters_dict
    state["final_letter"] = final_letters_dict.get(first_v) or final_letters_dict.get(draft_vendor) or ""
    if refine_samples:
        state["refine_samples"] = refine_samples
    state["status"] = STATUS_DONE
    state["cost"] = state.get("cost", 0) + total_cost
    save_agentic_state(session, state)
    return state
