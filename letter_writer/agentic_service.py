"""
Per-topic agentic flow: one draft model, feedback threads per topic (instruction, accuracy, etc.),
multiple feedback agents in random order per round, comments/subcomments/addendums/votes, then rewrite.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

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
from .phased_service import get_effective_additional_user_info, get_metadata_field
from .cost_tracker import track_api_cost
from .retrieval import select_top_documents
from .research import company_research
from .typed_shapes import TopDocument


def _top_docs_missing_letter_text(top_docs: Sequence[TopDocument]) -> bool:
    if not top_docs:
        return False
    return any(not (d.get("letter_text") or "").strip() for d in top_docs)


def _refresh_top_docs_from_session_search_if_needed(
    session,
    job_text: str,
    metadata: dict,
    vendor: str,
    top_docs: List[TopDocument],
) -> List[TopDocument]:
    """Replace slim client top_docs with reranked docs that include job/letter text when possible."""
    if not _top_docs_missing_letter_text(top_docs):
        return top_docs
    search_result = session.get("search_result", [])
    if not search_result:
        return top_docs
    company_name = get_metadata_field(metadata, ModelVendor(vendor), "company_name", "Unknown")
    trace_dir = Path("trace", f"{company_name}.agentic.top_docs_refresh")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(ModelVendor(vendor))
    result = select_top_documents(search_result, job_text, ai_client, trace_dir)
    return result.get("top_docs", []) or top_docs


# Status values for agentic state
STATUS_DRAFT = "draft"
STATUS_FEEDBACK = "feedback"
STATUS_FEEDBACK_DONE = "feedback_done"
STATUS_DONE = "done"

DEFAULT_MAX_ROUNDS = 3
# Server-side bounds for agentic feedback depth (client requests are clamped; persisted max_rounds is authoritative).
AGENTIC_MIN_MAX_ROUNDS = 1
AGENTIC_MAX_ROUNDS_CAP = 15
# After A1 top-level comments, run this many (add subcomments → vote/prune) cycles before addendums (A3).
DEFAULT_SUB_COMMENT_ROUNDS = 0
AGENTIC_MAX_SUB_COMMENT_ROUNDS_CAP = 8
MAX_POSITIVE_COMMENTS = 5
MIN_ROUNDS_BEFORE_DONE = 2  # require at least 2 full rounds (2 interactions per vendor) before we can stop
# If the client does not send a poll request for this many seconds, we abort (client likely left).
# This is about browser not polling, not about agents taking long to respond.

PHASE_A1 = "a1_top_comments"
PHASE_A2A1 = "a2a1_subcomments_add"
PHASE_A2A2 = "a2a2_subcomments_vote"
PHASE_A2B1 = "a2b1_subcomments_add"
PHASE_A2B2 = "a2b2_subcomments_vote"
PHASE_A3 = "a3_addendums"
PHASE_B = "b_global_votes"

PHASES_SUBCOMMENT_ADD = frozenset({PHASE_A2A1, PHASE_A2B1})
PHASES_SUBCOMMENT_VOTE = frozenset({PHASE_A2A2, PHASE_A2B2})

# Rotate API phase keys for successive sub-comment cycles (prompt/schema are identical per role).
SUBCOMMENT_PHASE_KEY_PAIRS: List[Tuple[str, str]] = [
    (PHASE_A2A1, PHASE_A2A2),
    (PHASE_A2B1, PHASE_A2B2),
]


def build_agentic_phase_a_labels(sub_comment_rounds: int) -> List[Tuple[str, str]]:
    """Phase-A pipeline: top-level comments, then N×(subcomment add, vote), then addendums.

    Display labels are semantic and fixed at the ends; only the middle steps vary with N.
    """
    out: List[Tuple[str, str]] = [(PHASE_A1, "Top-level comments")]
    try:
        n = int(sub_comment_rounds)
    except (TypeError, ValueError):
        n = DEFAULT_SUB_COMMENT_ROUNDS
    n = max(0, min(n, AGENTIC_MAX_SUB_COMMENT_ROUNDS_CAP))
    m = len(SUBCOMMENT_PHASE_KEY_PAIRS)
    for i in range(n):
        add_ph, vote_ph = SUBCOMMENT_PHASE_KEY_PAIRS[i % m]
        if n > 1:
            k = i + 1
            add_lbl = f"Sub-comments ({k}/{n})"
            vote_lbl = f"Sub-comment votes ({k}/{n})"
        else:
            add_lbl = "Sub-comments"
            vote_lbl = "Sub-comment votes"
        out.append((add_ph, add_lbl))
        out.append((vote_ph, vote_lbl))
    out.append((PHASE_A3, "Edit suggestions"))
    return out


SCHEMA_A1 = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "new_comment": {"type": "string"},
    },
    "required": ["new_comment"],
}

SCHEMA_A2 = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "subcomments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "comment_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["comment_id", "text"],
            },
        },
    },
    "required": ["subcomments"],
}

SCHEMA_A2_SUB_VOTE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "subcomment_votes": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["upvote", "downvote", "abstain"]},
                    "reason": {"type": "string"},
                },
                "required": ["action", "reason"],
            },
        },
    },
    "required": ["subcomment_votes"],
}

SCHEMA_A3 = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "addendums": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "comment_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["comment_id", "text"],
            },
        },
    },
    "required": ["addendums"],
}

SCHEMA_B = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "votes": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["upvote", "downvote", "abstain"]},
                    "reason": {"type": "string"},
                },
                "required": ["action", "reason"],
            },
        },
    },
    "required": ["votes"],
}


def build_phase_b_schema(
    threads: Dict[str, List[Dict[str, Any]]],
    active_topics: List[str],
) -> Dict[str, Any]:
    """Build a strict Phase B schema constrained to ids currently present in threads.

    .. deprecated:: Use :func:`build_phase_b_schema_for_topic` for the
       per-tuple Phase B calls.
    """
    comment_ids: List[str] = []
    addendum_pairs: List[Tuple[str, str]] = []
    seen_cids: set = set()
    for topic in active_topics:
        for c in threads.get(topic) or []:
            cid = c.get("id")
            if isinstance(cid, str) and cid and cid not in seen_cids:
                seen_cids.add(cid)
                comment_ids.append(cid)
            for a in c.get("addendums") or []:
                aid = a.get("id")
                if isinstance(cid, str) and cid and isinstance(aid, str) and aid:
                    addendum_pairs.append((cid, aid))

    return _build_vote_schema(comment_ids, addendum_pairs, active_topics)


def build_phase_b_schema_for_topic(
    thread: List[Dict[str, Any]],
    target_topic: str,
) -> Dict[str, Any]:
    """Strict Phase B schema scoped to a single target topic's ids."""
    comment_ids: List[str] = []
    addendum_pairs: List[Tuple[str, str]] = []
    for c in thread:
        if _is_comment_removed(c):
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        comment_ids.append(cid)
        for a in c.get("addendums") or []:
            aid = a.get("id")
            if isinstance(aid, str) and aid:
                addendum_pairs.append((cid, aid))
    return _build_vote_schema(comment_ids, addendum_pairs, [target_topic])


def _build_vote_schema(
    comment_ids: List[str],
    addendum_pairs: List[Tuple[str, str]],
    topics: List[str],  # kept for callers but no longer embedded in the schema
) -> Dict[str, Any]:
    """Object-keyed Phase B voting schema.

    Keys: ``"c::{comment_id}"`` for top-level comments,
          ``"a::{comment_id}::{addendum_id}"`` for addendums.
    All expected keys appear in ``required``, so the model must supply an
    action+reason for every item exactly once — duplication is impossible
    because JSON object keys are unique.
    """
    vote_item: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["upvote", "downvote", "abstain"]},
            "reason": {"type": "string"},
        },
        "required": ["action", "reason"],
    }
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for cid in comment_ids:
        key = f"c::{cid}"
        properties[key] = vote_item
        required.append(key)
    for cid, aid in addendum_pairs:
        key = f"a::{cid}::{aid}"
        properties[key] = vote_item
        required.append(key)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "votes": {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": required,
            }
        },
        "required": ["votes"],
    }


def format_topic_thread_for_voting(
    thread: List[Dict[str, Any]],
    topic: str,
) -> str:
    """Format a single topic's thread for the Phase B voting prompt."""
    lines: List[str] = []
    for c in thread:
        if _is_comment_removed(c):
            continue
        cid = c.get("id", "")
        lines.append(f"Comment topic={topic} id={cid} by {c.get('vendor', '?')}: {c.get('text', '')}")
        for a in c.get("addendums") or []:
            aid = a.get("id", "")
            lines.append(
                f"  Addendum topic={topic} comment_id={cid} addendum_id={aid} by {a.get('vendor', '?')}: {a.get('text', '')}"
            )
        for s in c.get("subcomments") or []:
            sid = s.get("id", "")
            lines.append(
                f"  Subcomment topic={topic} comment_id={cid} subcomment_id={sid} by {s.get('vendor', '?')}: {s.get('text', '')}"
            )
    return "\n".join(lines).strip() or "(No comments)"


def list_subcomment_vote_targets(thread: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Stable-order (comment_id, subcomment_id) pairs for subcomments eligible for voting."""
    out: List[Tuple[str, str]] = []
    for c in thread or []:
        if _is_comment_removed(c):
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        for s in c.get("subcomments") or []:
            sid = s.get("id")
            if isinstance(sid, str) and sid:
                out.append((cid, sid))
    return out


def build_phase_subcomment_vote_schema(thread: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Object-keyed schema for subcomment votes.

    Keys: ``"{comment_id}::{subcomment_id}"``, value: ``{action, reason}``.
    All expected keys are in ``required`` — the model must fill every one and
    cannot duplicate (object keys are unique by definition).
    """
    targets = list_subcomment_vote_targets(thread)
    vote_item: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["upvote", "downvote", "abstain"]},
            "reason": {"type": "string"},
        },
        "required": ["action", "reason"],
    }
    properties = {f"{cid}::{sid}": vote_item for cid, sid in targets}
    required = [f"{cid}::{sid}" for cid, sid in targets]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subcomment_votes": {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": required,
            }
        },
        "required": ["subcomment_votes"],
    }


def _require_session(session) -> None:
    """Raise if session is missing or invalid."""
    if not session:
        raise ValueError("Session is required")


def _user_id(session) -> str:
    """Return authenticated user id for cost tracking, or 'anonymous'."""
    return (session.get("user") or {}).get("id") or "anonymous"


def apply_server_max_rounds_policy(requested: Optional[int]) -> int:
    """Clamp client-requested max_rounds to server policy. Persisted state uses this value only."""
    if requested is None:
        return DEFAULT_MAX_ROUNDS
    try:
        r = int(requested)
    except (TypeError, ValueError):
        logger.warning(
            "agentic max_rounds invalid value %r; using default %s (server)",
            requested,
            DEFAULT_MAX_ROUNDS,
        )
        return DEFAULT_MAX_ROUNDS
    if r < AGENTIC_MIN_MAX_ROUNDS:
        logger.warning(
            "agentic max_rounds %s below server minimum %s; clamped (server source of truth)",
            r,
            AGENTIC_MIN_MAX_ROUNDS,
        )
        return AGENTIC_MIN_MAX_ROUNDS
    if r > AGENTIC_MAX_ROUNDS_CAP:
        logger.warning(
            "agentic max_rounds %s above server cap %s; clamped (server source of truth)",
            r,
            AGENTIC_MAX_ROUNDS_CAP,
        )
        return AGENTIC_MAX_ROUNDS_CAP
    return r


def apply_server_sub_comment_rounds_policy(requested: Optional[int]) -> int:
    """Clamp client-requested sub-comment cycles per main round (add+vote each). Default 0."""
    if requested is None:
        return DEFAULT_SUB_COMMENT_ROUNDS
    try:
        r = int(requested)
    except (TypeError, ValueError):
        logger.warning(
            "agentic sub_comment_rounds invalid value %r; using default %s (server)",
            requested,
            DEFAULT_SUB_COMMENT_ROUNDS,
        )
        return DEFAULT_SUB_COMMENT_ROUNDS
    if r < 0:
        logger.warning(
            "agentic sub_comment_rounds %s below 0; clamped (server source of truth)",
            r,
        )
        return 0
    if r > AGENTIC_MAX_SUB_COMMENT_ROUNDS_CAP:
        logger.warning(
            "agentic sub_comment_rounds %s above server cap %s; clamped (server source of truth)",
            r,
            AGENTIC_MAX_SUB_COMMENT_ROUNDS_CAP,
        )
        return AGENTIC_MAX_SUB_COMMENT_ROUNDS_CAP
    return r


def warn_agentic_round_limit_issues(state: Optional[Dict[str, Any]]) -> None:
    """Log warnings when topic cursors exceed backend limits or client draft hint vs server max_rounds."""
    if not state:
        return
    mr = _get_max_rounds(state)
    cursors = state.get("topic_cursors") or {}
    hint = state.get("client_max_rounds_requested")
    if hint is not None:
        try:
            h = int(hint)
        except (TypeError, ValueError):
            h = None
        if h is not None and mr > h:
            logger.warning(
                "agentic persisted max_rounds=%s exceeds client draft hint %s (e.g. Add round); server is source of truth",
                mr,
                h,
            )
    for topic in AGENTIC_TOPIC_KEYS:
        cur = cursors.get(topic) or {}
        try:
            r = int(cur.get("round", 1) or 1)
        except Exception as e:
            logger.warning("round parse failed for topic=%s: %s", topic, e)
            r = 1
        if r > mr + 1:
            logger.warning(
                "agentic topic=%s cursor round=%s exceeds max_rounds=%s + 1 (unexpected; check worker)",
                topic,
                r,
                mr,
            )


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
    "sub_comment_rounds",
    "vendor_errors", "draft_votes", "refine_samples",
)


def _get_max_rounds(state: Optional[Dict[str, Any]]) -> int:
    """Return configured max_rounds for this run (default DEFAULT_MAX_ROUNDS)."""
    if not state:
        return DEFAULT_MAX_ROUNDS
    return int(state.get("max_rounds") or DEFAULT_MAX_ROUNDS)


def _get_sub_comment_rounds(state: Optional[Dict[str, Any]]) -> int:
    """Return sub-comment (add+vote) cycles per main commenting round (default 0)."""
    if not state:
        return DEFAULT_SUB_COMMENT_ROUNDS
    raw = state.get("sub_comment_rounds")
    if raw is None:
        return DEFAULT_SUB_COMMENT_ROUNDS
    try:
        r = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SUB_COMMENT_ROUNDS
    return max(0, min(r, AGENTIC_MAX_SUB_COMMENT_ROUNDS_CAP))


def feedback_rounds_exhausted(state: Optional[Dict[str, Any]]) -> bool:
    """True when every topic cursor has round > max_rounds (same rule as topic_meta.done for all topics)."""
    if not state:
        return False
    max_rounds = _get_max_rounds(state)
    cursors = state.get("topic_cursors") or {}
    for topic in AGENTIC_TOPIC_KEYS:
        cur = cursors.get(topic) or {}
        try:
            r = int(cur.get("round", 1) or 1)
        except Exception as e:
            logger.warning("round parse failed for topic=%s: %s", topic, e)
            r = 1
        if r <= max_rounds:
            return False
    return True


def normalize_agentic_feedback_if_rounds_exhausted(state: Optional[Dict[str, Any]]) -> bool:
    """If all topics are past max rounds but status/ongoing still say work is in progress, fix flags.

    The ordered worker normally sets feedback_done when active_topics is empty; this covers races or
    desync where the UI already shows every topic done but voting would still reject.
    """
    if not state:
        return False
    if not feedback_rounds_exhausted(state):
        return False
    if state.get("status") not in (STATUS_FEEDBACK, STATUS_FEEDBACK_DONE):
        return False
    changed = False
    if state.get("feedback_ongoing"):
        state["feedback_ongoing"] = False
        changed = True
    if state.get("worker_running"):
        state["worker_running"] = False
        changed = True
    if state.get("status") == STATUS_FEEDBACK:
        state["status"] = STATUS_FEEDBACK_DONE
        changed = True
    return changed


def agentic_topic_human_label(topic: str) -> str:
    """Short display label for a topic key (matches frontend topic column titles)."""
    return {
        "instruction": "Instruction",
        "company_fit": "Company fit",
        "precision": "Precision",
        "user_fit": "User fit",
        "human": "Human",
        "accuracy": "CV accuracy",
    }.get(topic, topic)


def clear_phase_progress(state: Optional[Dict[str, Any]]) -> None:
    """Remove phase-progress tracking; call when the feedback worker stops."""
    if not state:
        return
    state.pop("phase_progress", None)


def _build_topic_meta(state: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build per-topic meta for UI: round, messages, done (round > max_rounds), optional waiting_for."""
    if not state:
        return {}
    threads = state.get("threads") or _empty_threads()
    cursors = state.get("topic_cursors") or {}
    max_rounds = _get_max_rounds(state)
    feedback_on = bool(state.get("feedback_ongoing"))

    # Structured progress set by individual worker threads:
    #   Phase A task key: "{topic}::{vendor}"           (2 parts)
    #   Phase B task key: "{src}::{target}::{vendor}"   (3 parts)
    progress = state.get("phase_progress") or {}
    phase_label = progress.get("phase") or ""
    phase_round = int(progress.get("round") or 1)
    tasks: Dict[str, bool] = progress.get("tasks") or {}

    out = {}
    for topic in AGENTIC_TOPIC_KEYS:
        cur = cursors.get(topic) or {}
        r = cur.get("round", 1)
        done = r > max_rounds
        entry: Dict[str, Any] = {
            "round": r,
            "messages": len(threads.get(topic) or []),
            "done": done,
        }
        if feedback_on and not done and tasks:
            pending: List[str] = []
            completed: List[str] = []
            for key, is_done in tasks.items():
                parts = key.split("::")
                if len(parts) == 2 and parts[0] == topic:
                    # Phase A: "{topic}::{vendor}"
                    (completed if is_done else pending).append(parts[1])
                elif len(parts) == 3 and parts[1] == topic:
                    # Phase B: "{src}::{target}::{vendor}"
                    label = f"{parts[0]}:{parts[2]}"
                    (completed if is_done else pending).append(label)
            if pending or completed:
                entry["waiting_for"] = {
                    "phase": phase_label,
                    "round": phase_round,
                    "pending": sorted(pending),
                    "done": sorted(completed),
                }
        out[topic] = entry
    return out


def slim_agentic_state_for_response(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a minimal state for API responses so we don't send cached heavy data."""
    if state is None:
        return None
    result = {k: state.get(k) for k in AGENTIC_STATE_RESPONSE_KEYS if k in state}
    result["topic_meta"] = _build_topic_meta(state)
    result["max_rounds"] = _get_max_rounds(state)
    result["sub_comment_rounds"] = _get_sub_comment_rounds(state)
    if "feedback_suspended" not in result and state.get("feedback_suspended") is not None:
        result["feedback_suspended"] = state.get("feedback_suspended")
    return result


def poll_response(
    state: Optional[Dict[str, Any]],
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
        tm = topic_meta.get(topic) or {}
        threads[topic] = {
            "thread": [{**c, "removed": _is_comment_removed(c)} for c in (raw_threads.get(topic) or [])],
            "round": tm.get("round", 1),
            "messages": tm.get("messages", len(raw_threads.get(topic) or [])),
            "done": tm.get("done", False),
            "waiting_for": tm.get("waiting_for"),
        }
    return {
        "threads": threads,
        "ongoing": ongoing,
        "status": status,
        "feedback_suspended": feedback_suspended,
        "max_rounds": _get_max_rounds(state),
        "sub_comment_rounds": _get_sub_comment_rounds(state),
        "vendor_errors": state.get("vendor_errors", {}),
    }


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


# ---------------------------------------------------------------------------
# Agentic feedback flow — architecture overview
# ---------------------------------------------------------------------------
#
# One "round" consists of:
#
#   Phase A  (per-topic, no cross-topic sync)
#   ─────────────────────────────────────────
#   Each topic runs its own independent pipeline of sub-phases:
#     — Top-level comments (one optional comment per vendor)
#     — Zero or more cycles of: sub-comments → vote/prune (count = ``sub_comment_rounds``)
#     — Edit-suggestion addendums
#   Topics run concurrently.  Within a topic, sub-phases are sequential.
#   All vendors for a given topic + sub-phase run in parallel.
#
#   Sync barrier
#   ────────────
#   All topics must finish Phase A before any topic enters Phase B.
#
#   Phase B  (per-tuple cross-topic voting)
#   ────────────────────────────────────────
#   For every (vendor, source_topic, target_topic) tuple:
#     - The vendor acts in the *context* of source_topic
#     - The vendor votes on comments/addendums from target_topic
#   All tuples run fully in parallel.  This ensures every vendor
#   evaluates every topic's comments from every perspective, and no
#   topic is accidentally skipped.
#   ``apply_global_votes_and_prune`` records those votes into each
#   comment's ``votes`` (aggregate) and ``votes_by_round`` (per-round
#   snapshot keyed ``"{topic}::{round}"``).
#
# Then the round counter increments and the loop repeats.
#
# Vote storage
# ────────────
# Each top-level comment carries two vote structures:
#   c["votes"]           — aggregate {up: [], down: [], abstain: []}.
#                          Reflects each vendor's *latest* position
#                          (used for net-score and prompt display).
#   c["votes_by_round"]  — dict keyed by "{topic}::{round}" →
#                          {up: [], down: [], abstain: [], reasons: {},
#                           topic: str, round: int}.
#                          The UI renders one vote row per bucket.
#
# Deduplication
# ─────────────
# No dedup guards exist.  Each vendor is called exactly once per topic
# per round, so duplicates cannot arise.  Cross-round re-voting is
# intentional: a vendor may change its position every round and both
# positions are preserved in ``votes_by_round``.
#
# Prompt formatting
# ─────────────────
# Every non-removed comment is always marked OPEN so every vendor is
# prompted to act on it each round.
# ---------------------------------------------------------------------------


def _sanitize_vote_reason(raw: Any) -> str:
    """Normalize optional model-provided vote rationale to a short one-liner."""
    if not isinstance(raw, str):
        return ""
    compact = " ".join(raw.strip().split())
    return compact[:180]


def _ensure_vote_round_bucket(
    c: Dict[str, Any],
    round_num: Optional[int],
    topic: Optional[str] = None,
    source_topic: Optional[str] = None,
) -> Dict[str, Any]:
    """Return mutable per-round vote bucket for a comment.

    Key format:
      ``"{source_topic}::{target_topic}::{round}"`` — Phase B cross-topic vote
      ``"{target_topic}::{round}"``                — single-topic Phase A vote
      ``"{round}"``                                — legacy / no topic info
    """
    rn = int(round_num or c.get("created_round") or 1)
    rounds = c.setdefault("votes_by_round", {})
    if source_topic:
        # Phase B: key is the source perspective + round only.
        # The target topic is implicit — it is always the comment's own topic.
        key = f"{source_topic}::{rn}"
    elif topic:
        key = f"{topic}::{rn}"
    else:
        key = str(rn)
    bucket = rounds.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        rounds[key] = bucket
    bucket.setdefault("up", [])
    bucket.setdefault("down", [])
    bucket.setdefault("abstain", [])
    bucket.setdefault("reasons", {})
    if source_topic:
        # "topic" field = the source perspective (what's meaningful for the UI label).
        bucket.setdefault("topic", source_topic)
    elif topic:
        bucket.setdefault("topic", topic)
    bucket.setdefault("round", rn)
    return bucket


def _set_comment_vote_action(
    c: Dict[str, Any],
    vendor: str,
    action: str,
    *,
    round_num: Optional[int] = None,
    topic: Optional[str] = None,
    source_topic: Optional[str] = None,
    reason: str = "",
) -> bool:
    """Record one vendor's vote on a top-level comment.

    Updates two places:
      1. ``c["votes"]`` — aggregate tallies (latest position per vendor across
         all rounds; used for net-score calculations and prompt display).
      2. ``c["votes_by_round"][key]`` — per-round snapshot keyed by
         ``"{source_topic}::{target_topic}::{round}"`` for Phase B cross-topic
         votes, or ``"{target_topic}::{round}"`` for Phase A votes, so the UI
         can show vote history broken down by source perspective and round.

    Within each per-round bucket the vendor is deduplicated (latest position
    wins) to prevent the same vendor appearing in multiple buckets when Phase B
    produces several (source_topic, target_topic) calls for the same vendor.
    A vendor that voted "up" in one round may vote "down" in the next; both
    rounds are preserved in ``votes_by_round``.
    """
    if "votes" not in c or not isinstance(c.get("votes"), dict):
        c["votes"] = {"up": [], "down": [], "abstain": []}
    votes = c["votes"]
    votes.setdefault("up", [])
    votes.setdefault("down", [])
    votes.setdefault("abstain", [])

    # Update aggregate: vendor appears in exactly one bucket (latest position).
    for k in ("up", "down", "abstain"):
        if vendor in votes[k]:
            votes[k].remove(vendor)
    votes[action].append(vendor)

    # Update per-round bucket.  Deduplicate within the bucket: if the model
    # returns the same comment_id multiple times (e.g. to pad minItems), we
    # only record the first occurrence per vendor per bucket.
    bucket = _ensure_vote_round_bucket(c, round_num, topic=topic, source_topic=source_topic)
    for _a in ("up", "down", "abstain"):
        lst = bucket.setdefault(_a, [])
        if vendor in lst:
            lst.remove(vendor)
    bucket[action].append(vendor)

    # Store optional rationale.
    clean_reason = _sanitize_vote_reason(reason)
    if clean_reason:
        bucket.setdefault("reasons", {})[vendor] = clean_reason

    return True


def _is_comment_removed(c: Dict[str, Any]) -> bool:
    """A comment is removed if manually flagged OR downvotes are a strict majority."""
    if c.get("removed"):
        return True
    votes = c.get("votes") or {}
    up = len(votes.get("up") or [])
    down = len(votes.get("down") or [])
    return down > up


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
    """Legacy carry-over disabled: cross-topic coordination now happens in global Phase B."""
    _ = carry_topic, carry_id
    return dict(c)


def get_prior_topic_top_comments(
    threads: Dict[str, List[Dict[str, Any]]],
    topic: str,
    *,
    max_per_topic: int = 3,
) -> List[Dict[str, Any]]:
    """Legacy carry-over disabled: return no pre-seeded prior-topic comments."""
    _ = threads, topic, max_per_topic
    return []


def seed_thread_with_prior_topic_comments(
    thread: List[Dict[str, Any]],
    prior_comments: List[Dict[str, Any]],
) -> None:
    """Legacy carry-over disabled."""
    _ = thread, prior_comments


def merge_carryover_updates_and_strip(
    topic_thread: List[Dict[str, Any]],
    threads: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Legacy carry-over disabled: return the topic thread unchanged."""
    _ = threads
    return list(topic_thread or [])


def format_prior_topic_comments_for_prompt(prior_comments: List[Dict[str, Any]]) -> str:
    """Legacy carry-over disabled: no prior-topic injection text."""
    _ = prior_comments
    return "(Cross-topic carry-over disabled; global voting handles cross-topic interactions.)"


def _format_thread_for_prompt(
    thread: List[Dict],
    topic: str,
    feedback_vendors: Optional[List[str]] = None,
    current_vendor: Optional[str] = None,
) -> str:
    """Format current thread for the prompt.

    Every non-removed comment is always OPEN so every vendor is prompted to
    act on it each round.  Per-round deduplication is enforced when the
    response is applied (see ``_set_comment_vote_action``), not here.
    """
    if not thread:
        return "(No comments yet.)"
    lines = []
    for i, c in enumerate(thread):
        cid = c.get("id", f"c{i}")
        is_removed = _is_comment_removed(c)
        # Every non-removed comment is OPEN every round so all vendors can
        # vote / add subcomments each round.
        status = "REMOVED" if is_removed else "OPEN"
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
            sid = s.get("id", "?")
            sup = len(s.get("up") or [])
            sdown = len(s.get("down") or [])
            lines.append(
                f"  Subcomment [id={sid}] by {s.get('vendor', '?')} (votes up={sup}, down={sdown}): {s.get('text', '')}"
            )
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
        "Your response must be either: (1) your feedback text, or (2) exactly 'NO COMMENT' or 'SKIP'.\n"
        "Base factual claims only on the labeled sections in the context above; do not say something is absent "
        "from materials you were not given in this prompt."
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
        "- Suggest concrete changes where appropriate.\n"
        "Base factual claims only on the labeled sections in the context above; do not say something is absent "
        "from materials you were not given in this prompt.\n\n"
        "Order of actions:\n"
        "1) Optionally add one new top-level comment (only if you have an original, substantive point not already in the thread).\n"
        "2) For each NEW addendum listed in the thread (those under 'New addendums (you must upvote or downvote each)'): you must either upvote or downvote it by addendum_id. No new addendum text when voting existing addendums.\n"
        "3) For each OPEN top-level comment: choose exactly one of: upvote the comment, downvote the comment, abstain, add a subcomment, or add one addendum. Do not interact with FINALIZED or REMOVED comments.\n\n"
        "Hard rule: a top-level comment is removed from downstream rewrite inputs only if downvotes become a strict majority over upvotes.\n\n"
        "Abstain usage: use abstain only when the comment is not relevant to this topic.\n\n"
        "Consistency rule: when prior-topic comments contradict evidence in this topic, downvote the inconsistent comment to push it toward majority-down removal.\n\n"
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
    thread_str = _format_thread_for_prompt(
        thread,
        topic,
        feedback_vendors,
        current_vendor=vendor,
    )
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
    except json.JSONDecodeError as e:
        logger.warning("_parse_phase_response JSON parse failed: %s", e)
        return {"subcomments": [], "votes": [], "new_comment": None}
    subcomments = data.get("subcomments") or []
    votes = data.get("votes") or []
    new_comment = data.get("new_comment")
    if new_comment and isinstance(new_comment, str) and is_agentic_skip(new_comment):
        new_comment = None
    return {"subcomments": subcomments, "votes": votes, "new_comment": new_comment}


_GEMINI_SCHEMA_STRIP_KEYS = frozenset({
    "enum", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "format",
})


def _simplify_schema_for_gemini(node: Any) -> Any:
    """Recursively strip constraints that cause Gemini's 'too many states' error.

    Gemini rejects schemas with large enum lists (e.g. hex IDs), array length
    bounds (minItems/maxItems), and string matchers (minLength etc.).  Removing
    these still gives Gemini the structural shape it needs while staying within
    its serving constraint budget.
    """
    if isinstance(node, dict):
        return {
            k: _simplify_schema_for_gemini(v)
            for k, v in node.items()
            if k not in _GEMINI_SCHEMA_STRIP_KEYS
        }
    if isinstance(node, list):
        return [_simplify_schema_for_gemini(v) for v in node]
    return node


def _json_response_format(name: str, schema: Dict[str, Any], vendor: str) -> Dict[str, Any]:
    if vendor == "deepseek":
        return {"type": "json_object"}
    effective_schema = _simplify_schema_for_gemini(schema) if vendor == "gemini" else schema
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": effective_schema,
        },
    }


def _parse_structured_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except Exception as e:
        logger.warning("_parse_structured_json failed: %s", e)
        return {}
    return obj if isinstance(obj, dict) else {}


def _phase_prompt(
    phase: str,
    topic: str,
    context: str,
    thread_str: str = "",
    global_threads_str: str = "",
    *,
    subcomment_vote_count: Optional[int] = None,
) -> Tuple[str, str]:
    topic_label = _topic_label(topic)
    if phase == PHASE_A1:
        system = (
            f"You are a feedback agent for '{topic_label}'. "
            "Use only the provided response tool/schema. "
            "Return one optional top-level comment or null."
        )
        prompt = (
            context
            + "\n\nOnly propose one substantive top-level comment for this topic. "
            "If nothing substantive, return an empty string \"\"."
        )
        return system, prompt
    if phase in PHASES_SUBCOMMENT_ADD:
        system = (
            f"You are a feedback agent for '{topic_label}'. "
            "Use only the provided response tool/schema. "
            "You may only return subcomments."
        )
        prompt = (
            context
            + "\n\n========== Current topic thread ==========\n"
            + thread_str
            + "\n\nAdd only non-redundant subcomments to existing top-level comments."
        )
        return system, prompt
    if phase in PHASES_SUBCOMMENT_VOTE:
        n = int(subcomment_vote_count) if subcomment_vote_count is not None else 0
        system = (
            f"You are a feedback agent for '{topic_label}'. "
            "Use only the provided response tool/schema. "
            "You must return subcomment_votes only."
        )
        if n <= 0:
            prompt = (
                context
                + "\n\n========== Current topic thread ==========\n"
                + thread_str
                + "\n\nThere are no subcomments to vote on. Return subcomment_votes as an empty object {}."
            )
        else:
            prompt = (
                context
                + "\n\n========== Current topic thread ==========\n"
                + thread_str
                + f"\n\nThe subcomment_votes object has exactly {n} keys — one per subcomment above. "
                "You MUST fill every key. "
                "Set action to upvote (useful/accurate), downvote (redundant/noisy/wrong), or abstain. "
                "Every entry MUST include a non-empty reason: one short sentence explaining your vote. "
                "Subcomments with strict majority downvotes are removed after this phase."
            )
        return system, prompt
    if phase == PHASE_A3:
        system = (
            f"You are a feedback agent for '{topic_label}'. "
            "Use only the provided response tool/schema. "
            "You may only return edit suggestions (addendums) attached to existing top-level comments."
        )
        prompt = (
            context
            + "\n\n========== Current topic thread ==========\n"
            + thread_str
            + "\n\nSuggest concrete edits as addendums for existing comments only."
        )
        return system, prompt
    if phase == PHASE_B:
        system = (
            "You are a cross-topic voting agent. "
            "Use only the provided response tool/schema. "
            "The votes object has one key per comment and per addendum. "
            "You MUST fill every key — omitting any is not allowed."
        )
        prompt = (
            context
            + "\n\n========== Comments to vote on ==========\n"
            + global_threads_str
            + "\n\nIMPORTANT: Fill every key in the votes object with an action (upvote/downvote/abstain) "
            "and a non-empty reason. Every item must be covered — do not skip any."
        )
        return system, prompt
    return ("Use only the provided response tool/schema.", context)


def call_agentic_phase_action(
    *,
    vendor: str,
    phase: str,
    topic: str,
    context: str,
    thread: Optional[List[Dict[str, Any]]] = None,
    global_threads_str: str = "",
    schema_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = get_client(ModelVendor(vendor))
    if schema_override is not None:
        schema = schema_override
    elif phase == PHASE_A1:
        schema = SCHEMA_A1
    elif phase in PHASES_SUBCOMMENT_ADD:
        schema = SCHEMA_A2
    elif phase in PHASES_SUBCOMMENT_VOTE:
        schema = SCHEMA_A2_SUB_VOTE
    elif phase == PHASE_A3:
        schema = SCHEMA_A3
    else:
        schema = SCHEMA_B
    thread_str = _format_thread_for_prompt(thread or [], topic, current_vendor=vendor) if thread is not None else ""
    sub_n: Optional[int] = None
    if phase in PHASES_SUBCOMMENT_VOTE:
        sub_n = len(list_subcomment_vote_targets(thread or []))
    system, prompt = _phase_prompt(
        phase,
        topic,
        context,
        thread_str=thread_str,
        global_threads_str=global_threads_str,
        subcomment_vote_count=sub_n,
    )
    if vendor == "deepseek":
        prompt += f"\n\nYou must return a JSON object matching this schema:\n{json.dumps(schema)}"
    raw = client.call(
        ModelSize.TINY,
        system,
        [prompt],
        response_format=_json_response_format(f"feedback_{phase}", schema, vendor),
    )
    data = _parse_structured_json(raw)
    if phase == PHASE_A1:
        val = data.get("new_comment")
        return {"new_comment": val if isinstance(val, str) and val.strip() else None}
    if phase in PHASES_SUBCOMMENT_ADD:
        out = []
        for s in data.get("subcomments") or []:
            if not isinstance(s, dict):
                continue
            cid = s.get("comment_id")
            text = (s.get("text") or "").strip()
            if isinstance(cid, str) and text:
                out.append({"comment_id": cid, "text": text})
        return {"subcomments": out}
    if phase in PHASES_SUBCOMMENT_VOTE:
        expected = list_subcomment_vote_targets(thread or [])
        expected_set = set(expected)
        by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
        raw_votes = data.get("subcomment_votes") or {}
        if not isinstance(raw_votes, dict):
            logger.warning(
                "AGENTIC unexpected subcomment_votes type vendor=%s topic=%s type=%s",
                vendor, topic, type(raw_votes).__name__,
            )
            raw_votes = {}
        for key, v in raw_votes.items():
            if not isinstance(v, dict) or "::" not in key:
                continue
            cid, sid = key.split("::", 1)
            action = str(v.get("action") or "").lower()
            if action not in ("upvote", "downvote", "abstain"):
                continue
            reason = _sanitize_vote_reason(v.get("reason"))
            if not reason:
                continue
            pair = (cid, sid)
            if pair not in expected_set:
                continue
            by_pair[pair] = {
                "comment_id": cid,
                "subcomment_id": sid,
                "action": action,
                "reason": reason,
            }
        got = set(by_pair.keys())
        if got != expected_set:
            logger.warning(
                "AGENTIC subcomment vote coverage vendor=%s topic=%s expected_pairs=%s got_pairs=%s",
                vendor,
                topic,
                sorted(expected_set),
                sorted(got),
            )
        return {"subcomment_votes": list(by_pair.values())}
    if phase == PHASE_A3:
        out = []
        for a in data.get("addendums") or []:
            if not isinstance(a, dict):
                continue
            cid = a.get("comment_id")
            text = (a.get("text") or "").strip()
            if isinstance(cid, str) and text:
                out.append({"comment_id": cid, "text": text})
        return {"addendums": out}
    # Phase B: object-keyed votes.
    # Keys: "c::{comment_id}" for comments, "a::{comment_id}::{addendum_id}" for addendums.
    # topic is injected from call context (this function's `topic` param = target_topic).
    raw_votes = data.get("votes") or {}
    if not isinstance(raw_votes, dict):
        logger.warning(
            "AGENTIC unexpected votes type vendor=%s topic=%s type=%s",
            vendor, topic, type(raw_votes).__name__,
        )
        raw_votes = {}
    out_votes = []
    for item_key, v in raw_votes.items():
        if not isinstance(v, dict):
            continue
        action = str(v.get("action") or "").lower()
        if action not in ("upvote", "downvote", "abstain"):
            continue
        reason = str(v.get("reason") or "")
        if item_key.startswith("c::"):
            cid = item_key[3:]
            if not cid:
                continue
            out_votes.append({
                "topic": topic,
                "target_type": "comment",
                "comment_id": cid,
                "addendum_id": None,
                "action": action,
                "reason": reason,
            })
        elif item_key.startswith("a::"):
            rest = item_key[3:]
            if "::" not in rest:
                continue
            cid, aid = rest.split("::", 1)
            if not cid or not aid:
                continue
            out_votes.append({
                "topic": topic,
                "target_type": "addendum",
                "comment_id": cid,
                "addendum_id": aid,
                "action": action,
                "reason": reason,
            })
        else:
            logger.warning("AGENTIC unknown vote key vendor=%s topic=%s key=%r", vendor, topic, item_key)
    return {"votes": out_votes}


def apply_phase_a1_comment(
    thread: List[Dict[str, Any]],
    vendor: str,
    new_comment: Optional[str],
    *,
    round_num: int,
) -> bool:
    text = (new_comment or "").strip()
    if not text or is_agentic_skip(text):
        return False
    thread.append(
        {
            "id": str(uuid.uuid4())[:8],
            "vendor": vendor,
            "text": text,
            "addendums": [],
            "votes": {"up": [], "down": [], "abstain": []},
            "votes_by_round": {},
            "subcomments": [],
            "removed": False,
            "created_round": int(round_num or 1),
        }
    )
    return True


def apply_phase_subcomments(
    thread: List[Dict[str, Any]],
    vendor: str,
    subcomments: List[Dict[str, Any]],
) -> bool:
    id_to_idx = {c.get("id"): i for i, c in enumerate(thread) if c.get("id")}
    changed = False
    for sc in subcomments or []:
        cid = sc.get("comment_id")
        idx = id_to_idx.get(cid)
        if idx is None:
            continue
        if _is_comment_removed(thread[idx]):
            continue
        text = (sc.get("text") or "").strip()
        if not text:
            continue
        thread[idx].setdefault("subcomments", []).append(
            {
                "id": str(uuid.uuid4())[:8],
                "vendor": vendor,
                "text": text,
                "up": [],
                "down": [],
                "abstain": [],
                "reasons": {},
            }
        )
        changed = True
    return changed


def _apply_vendor_subcomment_vote(
    sub: Dict[str, Any],
    vendor: str,
    action: str,
    *,
    reason: str = "",
) -> None:
    sub.setdefault("up", [])
    sub.setdefault("down", [])
    sub.setdefault("abstain", [])
    clean = _sanitize_vote_reason(reason)
    if clean:
        sub.setdefault("reasons", {})[vendor] = clean
    if action == "upvote":
        if vendor in sub["down"]:
            sub["down"].remove(vendor)
        if vendor in sub["abstain"]:
            sub["abstain"].remove(vendor)
        if vendor not in sub["up"]:
            sub["up"].append(vendor)
    elif action == "downvote":
        if vendor in sub["up"]:
            sub["up"].remove(vendor)
        if vendor in sub["abstain"]:
            sub["abstain"].remove(vendor)
        if vendor not in sub["down"]:
            sub["down"].append(vendor)
    elif action == "abstain":
        if vendor in sub["up"]:
            sub["up"].remove(vendor)
        if vendor in sub["down"]:
            sub["down"].remove(vendor)
        if vendor not in sub["abstain"]:
            sub["abstain"].append(vendor)


def apply_phase_subcomment_votes(
    thread: List[Dict[str, Any]],
    vendor: str,
    subcomment_votes: List[Dict[str, Any]],
) -> bool:
    id_to_idx = {c.get("id"): i for i, c in enumerate(thread) if c.get("id")}
    changed = False
    for v in subcomment_votes or []:
        if not isinstance(v, dict):
            continue
        cid = v.get("comment_id")
        sid = v.get("subcomment_id")
        action = str(v.get("action") or "").lower()
        if not isinstance(cid, str) or not isinstance(sid, str):
            continue
        if action not in ("upvote", "downvote", "abstain"):
            continue
        idx = id_to_idx.get(cid)
        if idx is None or _is_comment_removed(thread[idx]):
            continue
        for s in thread[idx].get("subcomments") or []:
            if s.get("id") != sid:
                continue
            r = str(v.get("reason") or "")
            _apply_vendor_subcomment_vote(s, vendor, action, reason=r)
            changed = True
            break
    return changed


def prune_downvoted_subcomments(thread: List[Dict[str, Any]]) -> None:
    """Drop subcomments where downvotes strictly exceed upvotes (same rule as addendum pruning)."""
    for c in thread or []:
        if _is_comment_removed(c):
            continue
        subs = c.get("subcomments") or []
        kept: List[Dict[str, Any]] = []
        for s in subs:
            up = len(s.get("up") or [])
            down = len(s.get("down") or [])
            if down > up:
                continue
            kept.append(s)
        c["subcomments"] = kept


def apply_phase_addendums(
    thread: List[Dict[str, Any]],
    vendor: str,
    addendums: List[Dict[str, Any]],
) -> bool:
    id_to_idx = {c.get("id"): i for i, c in enumerate(thread) if c.get("id")}
    changed = False
    for ad in addendums or []:
        cid = ad.get("comment_id")
        idx = id_to_idx.get(cid)
        if idx is None:
            continue
        if _is_comment_removed(thread[idx]):
            continue
        text = (ad.get("text") or "").strip()
        if not text:
            continue
        thread[idx].setdefault("addendums", []).append(
            {
                "id": str(uuid.uuid4())[:8],
                "vendor": vendor,
                "text": text,
                "up": [vendor],
                "down": [],
            }
        )
        changed = True
    return changed


def format_global_threads_for_voting(
    threads: Dict[str, List[Dict[str, Any]]],
    active_topics: List[str],
) -> str:
    lines: List[str] = []
    for topic in AGENTIC_TOPIC_KEYS:
        if topic not in active_topics:
            continue
        lines.append(f"===== Topic: {topic} =====")
        for c in threads.get(topic) or []:
            if _is_comment_removed(c):
                continue
            cid = c.get("id", "")
            lines.append(f"Comment topic={topic} id={cid} by {c.get('vendor', '?')}: {c.get('text', '')}")
            for a in c.get("addendums") or []:
                aid = a.get("id", "")
                lines.append(
                    f"  Addendum topic={topic} comment_id={cid} addendum_id={aid} by {a.get('vendor', '?')}: {a.get('text', '')}"
                )
            for s in c.get("subcomments") or []:
                sid = s.get("id", "")
                lines.append(
                    f"  Subcomment topic={topic} comment_id={cid} subcomment_id={sid} by {s.get('vendor', '?')}: {s.get('text', '')}"
                )
        lines.append("")
    return "\n".join(lines).strip() or "(No comments)"


def apply_global_votes_and_prune(
    threads: Dict[str, List[Dict[str, Any]]],
    votes_payloads: List[Tuple[str, str, Dict[str, Any]]],
    *,
    round_num: int,
) -> None:
    for vendor, source_topic, payload in votes_payloads:
        for vote in payload.get("votes") or []:
            topic = vote.get("topic")
            if topic not in threads:
                continue
            action = vote.get("action")
            if action not in ("upvote", "downvote", "abstain"):
                continue
            thread = threads.get(topic) or []
            c = next((x for x in thread if x.get("id") == vote.get("comment_id")), None)
            if c is None or _is_comment_removed(c):
                continue
            target_type = vote.get("target_type")
            if target_type == "comment":
                mapped = "up" if action == "upvote" else ("down" if action == "downvote" else "abstain")
                _set_comment_vote_action(
                    c,
                    vendor,
                    mapped,
                    round_num=round_num,
                    topic=topic,
                    source_topic=source_topic or None,
                    reason=vote.get("reason") or "",
                )
                continue
            addendum_id = vote.get("addendum_id")
            if target_type == "addendum" and isinstance(addendum_id, str):
                for a in c.get("addendums") or []:
                    if a.get("id") != addendum_id:
                        continue
                    a.setdefault("up", [])
                    a.setdefault("down", [])
                    if action == "upvote" and vendor not in a["up"]:
                        a["up"].append(vendor)
                    if action == "downvote" and vendor not in a["down"]:
                        a["down"].append(vendor)
    for topic, thread in threads.items():
        for c in thread:
            if _is_comment_removed(c):
                c["removed"] = True
                continue
            kept = []
            for a in c.get("addendums") or []:
                up = len(a.get("up") or [])
                down = len(a.get("down") or [])
                if down > up:
                    continue
                kept.append(a)
            c["addendums"] = kept


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
    topic: Optional[str] = None,
    round_num: Optional[int] = None,
    new_comment_ids: Optional[List[str]] = None,
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
                "up": [],
                "down": [],
                "abstain": [],
                "reasons": {},
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
                topic=topic,
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
                topic=topic,
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
                addendum_by_id[str(new_a["id"])] = (idx, len(thread[idx]["addendums"]) - 1)
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
                    topic=topic,
                    reason=v.get("reason") or v.get("rationale") or "",
                ):
                    changed = True
                # Removal is decided by majority vote state (down > up); do not force-remove here.
    new_comment = response.get("new_comment")
    if new_comment and isinstance(new_comment, str) and new_comment.strip():
        new_comment_id = str(uuid.uuid4())[:8]
        thread.append({
            "id": new_comment_id,
            "vendor": vendor,
            "text": new_comment.strip(),
            "addendums": [],
            "votes": {"up": [], "down": [], "abstain": []},
            "votes_by_round": {},
            "subcomments": [],
            "removed": False,
            "created_round": int(round_num or 1),
        })
        # Voting is handled exclusively by Phase B cross-topic passes.
        # No implicit self-vote here.
        if new_comment_ids is not None:
            new_comment_ids.append(new_comment_id)
        changed = True
    return changed


def _filter_vote_only_response_for_comments(
    response: Dict[str, Any],
    allowed_comment_ids: List[str],
) -> Dict[str, Any]:
    """Keep only explicit top-level votes for allowed comments."""
    allowed = set(allowed_comment_ids)
    votes_out: List[Dict[str, Any]] = []
    for v in (response or {}).get("votes") or []:
        cid = v.get("comment_id")
        if cid is None:
            cid = v.get("commentId")
        if cid not in allowed:
            continue
        action_raw = str(v.get("action") or "").lower()
        if action_raw == "abstain":
            action = "abstain"
        elif action_raw == "upvote" or ("up" in action_raw and "down" not in action_raw):
            action = "upvote"
        elif action_raw == "downvote" or "down" in action_raw:
            action = "downvote"
        else:
            continue
        vote_row = {"comment_id": cid, "action": action}
        reason = v.get("reason") or v.get("rationale")
        if isinstance(reason, str) and reason.strip():
            vote_row["reason"] = reason.strip()
        votes_out.append(vote_row)
    return {"subcomments": [], "votes": votes_out, "new_comment": None}


def _run_immediate_vote_sweep_for_comments(
    thread: List[Dict[str, Any]],
    topic: str,
    context: str,
    vendors: List[str],
    trace_dir: Path,
    *,
    prior_topic_comments_text: str = "",
    source_vendor: Optional[str] = None,
    comment_ids: Optional[List[str]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
    round_num: Optional[int] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Immediately call all AIs to vote on newly proposed comments.
    We accept only explicit top-level votes on the target comments.
    """
    target_ids = [cid for cid in (comment_ids or []) if cid]
    if not target_ids:
        return False
    changed = False
    for voter in vendors:
        if should_abort is not None and should_abort():
            _log(f"AGENTIC topic={topic}: abort during immediate vote sweep before voter={voter}")
            break
        if source_vendor and voter == source_vendor:
            # The proposing agent is called in normal sequence already; we do not auto-mark a vote.
            continue
        pending_for_voter = []
        for c in thread:
            cid = c.get("id")
            if cid in target_ids and not c.get("removed"):
                pending_for_voter.append(cid)
        if not pending_for_voter:
            continue
        try:
            if on_progress:
                on_progress(
                    f"Vote-only LLM API ({voter}); comment id(s): {', '.join(pending_for_voter)}"
                )
            _log(f"AGENTIC immediate vote sweep: topic={topic} voter={voter} pending={pending_for_voter}")
            raw_response = _call_agentic_feedback_agent(
                voter,
                topic,
                context,
                thread,
                trace_dir,
                feedback_vendors=vendors,
                prior_topic_comments=prior_topic_comments_text,
            )
            vote_only_response = _filter_vote_only_response_for_comments(raw_response, pending_for_voter)
            if _apply_agent_response(
                thread,
                voter,
                vote_only_response,
                topic=topic,
                round_num=round_num,
                new_comment_ids=None,
            ):
                changed = True
        except Exception as e:
            _log(f"AGENTIC immediate vote sweep error topic={topic} voter={voter}: {e}")
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
    except json.JSONDecodeError as e:
        logger.warning("votes JSON parse failed: %s", e)
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
    if normalize_agentic_feedback_if_rounds_exhausted(state):
        save_agentic_state(session, state)
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


def _default_refine_sample_n() -> int:
    """How many draft letters to sample as references during refine (env override, clamped)."""
    raw = (os.getenv("AGENTIC_REFINE_SAMPLE_COUNT") or "2").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(1, min(20, n))


def _sample_drafts_for_vendor(
    draft_letters: Dict[str, str],
    draft_votes: Dict[str, int],
    target_vendor: str,
    num_agents: int,
    n: int = 2,
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
    style_instructions: str = "",
    max_rounds: Optional[int] = None,
    sub_comment_rounds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate the draft letter with the given vendor and store agentic state.
    Uses session common data; reads example letters from ``session["selected_top_docs"]`` (job intake).
    If company_report or those examples are missing, runs background-style retrieval for draft_vendor.
    """
    _require_session(session)
    job_text = session.get("job_text", "")
    cv_text = session.get("cv_text", "")
    metadata = session.get("metadata", {})
    raw_sel = session.get("selected_top_docs") or []
    top_docs: List[TopDocument] = cast(List[TopDocument], list(raw_sel)) if raw_sel else []
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
            ) or ""

    top_docs = _refresh_top_docs_from_session_search_if_needed(
        session, job_text, metadata, draft_vendor, top_docs
    )

    if not style_instructions:
        style_instructions = session.get("style_instructions", "") or get_style_instructions()
    additional_user_info = get_effective_additional_user_info(
        metadata, ModelVendor(draft_vendor), _user_id(session)
    )

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
    state["client_max_rounds_requested"] = max_rounds
    state["max_rounds"] = apply_server_max_rounds_policy(max_rounds)
    state["sub_comment_rounds"] = apply_server_sub_comment_rounds_policy(sub_comment_rounds)
    save_agentic_state(session, state)
    if cost > 0:
        track_api_cost(_user_id(session), "draft", draft_vendor, cost)
    return state


def run_agentic_draft_multi(
    session,
    draft_vendors: List[str],
    company_report_override: Optional[str] = None,
    style_instructions: str = "",
    max_rounds: Optional[int] = None,
    sub_comment_rounds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate one draft letter per selected vendor and store in state as draft_letters.
    Uses session common data; reads example letters from ``session["selected_top_docs"]``.
    Runs background-style retrieval once (first vendor) if company_report or examples are missing.
    """
    _require_session(session)
    if not draft_vendors:
        raise ValueError("draft_vendors must be non-empty")
    job_text = session.get("job_text", "")
    cv_text = session.get("cv_text", "")
    metadata = session.get("metadata", {})
    raw_sel = session.get("selected_top_docs") or []
    top_docs: List[TopDocument] = cast(List[TopDocument], list(raw_sel)) if raw_sel else []
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
            ) or ""
        # #region agent log
        try:
            import json
            with open("/home/fdondi/Documents/#GitHub/letter-writer/.cursor/debug-5b1b21.log", "a") as _f:
                _f.write(json.dumps({"sessionId": "5b1b21", "hypothesisId": "H4", "location": "agentic_service.py:run_agentic_draft_multi", "message": "after company_research", "data": {"company_report_is_none": company_report is None, "company_report_type": type(company_report).__name__}, "timestamp": __import__("time").time() * 1000}) + "\n")
        except Exception:
            pass
        # #endregion

    top_docs = _refresh_top_docs_from_session_search_if_needed(
        session, job_text, metadata, first_vendor, top_docs
    )

    if not style_instructions:
        style_instructions = session.get("style_instructions", "") or get_style_instructions()

    draft_letters_dict: Dict[str, str] = {}
    vendor_errors: Dict[str, str] = {}
    total_cost = 0.0

    uid = _user_id(session)

    def _one_draft(vendor: str) -> Tuple[str, str, float]:
        trace_dir = Path("trace", "agentic.draft")
        trace_dir.mkdir(parents=True, exist_ok=True)
        additional_user_info = get_effective_additional_user_info(metadata, ModelVendor(vendor), uid)
        ai_client = get_client(ModelVendor(vendor))
        letter = generate_letter(
            cv_text, top_docs, company_report, job_text, ai_client, trace_dir,
            style_instructions, additional_user_info,
        )
        cost = getattr(ai_client, "total_cost", 0.0) or 0.0
        return (vendor, letter, cost)

    with ThreadPoolExecutor(max_workers=min(len(draft_vendors), 4)) as executor:
        futures = {executor.submit(_one_draft, v): v for v in draft_vendors}
        for fut in as_completed(futures):
            vendor = futures[fut]
            try:
                vendor, letter, cost = fut.result()
                draft_letters_dict[vendor] = letter
                total_cost += cost
                if cost > 0:
                    track_api_cost(uid, "draft", vendor, cost)
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
    state["client_max_rounds_requested"] = max_rounds
    state["max_rounds"] = apply_server_max_rounds_policy(max_rounds)
    state["sub_comment_rounds"] = apply_server_sub_comment_rounds_policy(sub_comment_rounds)
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
    # top_docs persisted in agentic state: trusted as List[TopDocument] once draft has run.
    top_docs = cast(List[TopDocument], state.get("top_docs") or [])
    company_report = state.get("company_report") or ""
    job_text = state.get("job_text") or ""
    cv_text = state.get("cv_text") or ""
    metadata = state.get("metadata") or {}
    style_instructions = state.get("style_instructions") or get_style_instructions()
    additional_user_info = get_effective_additional_user_info(
        metadata, ModelVendor(draft_vendor), _user_id(session)
    )

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
                new_comment_ids: List[str] = []
                if _apply_agent_response(
                    thread,
                    vendor,
                    response,
                    topic=topic,
                    round_num=round_num,
                    new_comment_ids=new_comment_ids,
                ):
                    any_change = True
                if new_comment_ids:
                    if _run_immediate_vote_sweep_for_comments(
                        thread,
                        topic,
                        context,
                        order,
                        trace_dir,
                        prior_topic_comments_text=prior_comments_text,
                        source_vendor=vendor,
                        comment_ids=new_comment_ids,
                        round_num=round_num,
                    ):
                        any_change = True
            except Exception as e:
                _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
                state.setdefault("vendor_errors", {})[vendor] = f"Error in topic {topic}: {e}"
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
    clear_phase_progress(state)
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
        current = int(state.get("max_rounds") or DEFAULT_MAX_ROUNDS)
        if current >= AGENTIC_MAX_ROUNDS_CAP:
            logger.warning(
                "agentic add round ignored: max_rounds already at server cap %s",
                AGENTIC_MAX_ROUNDS_CAP,
            )
            return
        state["max_rounds"] = current + 1
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
        _apply_agent_response(thread_copy, vendor, response, topic=topic, round_num=round_num)
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
    initial_vote_comment_ids: Optional[List[str]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    phase_label: str = "",
) -> Tuple[str, List[Dict], bool]:
    """Run all vendors for one topic sequentially so each agent sees previous addendums. Returns (topic, updated_thread)."""

    def _emit(detail: str) -> None:
        if on_progress:
            full = f"{phase_label} — {detail}" if phase_label else detail
            on_progress(full)

    # At topic start, force an explicit vote-only sweep on all carried comments so
    # every vendor gets a chance to reassess prior-topic comments with new context.
    target_ids = [cid for cid in (initial_vote_comment_ids or []) if cid]
    if target_ids:
        _emit(
            f"Vote-only sweep: reconciling {len(target_ids)} carried comment(s) "
            f"(one LLM call per vendor except skips)"
        )
        _run_immediate_vote_sweep_for_comments(
            thread,
            topic,
            context,
            vendor_order,
            trace_dir,
            prior_topic_comments_text=prior_topic_comments_text,
            source_vendor=None,
            comment_ids=target_ids,
            should_abort=should_abort,
            round_num=round_num,
            on_progress=_emit if on_progress else None,
        )

    n_v = len(vendor_order)
    for i, vendor in enumerate(vendor_order):
        if should_abort is not None and should_abort():
            _log(f"AGENTIC topic={topic}: abort before vendor={vendor} due to stale polling heartbeat")
            return (topic, thread, False)
        _emit(f"Full feedback LLM API ({vendor}); step {i + 1}/{n_v} in vendor chain")
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
            new_comment_ids: List[str] = []
            _apply_agent_response(
                thread,
                vendor,
                response,
                topic=topic,
                round_num=round_num,
                new_comment_ids=new_comment_ids,
            )
            if new_comment_ids:
                _emit(
                    f"Vote-only sweep after new comment from {vendor}: "
                    f"{len(new_comment_ids)} id(s); one LLM per other vendor"
                )
                _run_immediate_vote_sweep_for_comments(
                    thread,
                    topic,
                    context,
                    vendor_order,
                    trace_dir,
                    prior_topic_comments_text=prior_topic_comments_text,
                    source_vendor=vendor,
                    comment_ids=new_comment_ids,
                    should_abort=should_abort,
                    round_num=round_num,
                    on_progress=_emit if on_progress else None,
                )
        except Exception as e:
            _log(f"AGENTIC feedback agent error topic={topic} vendor={vendor}: {e}")
    return (topic, thread, True)


def run_agentic_feedback_step(
    session,
) -> Tuple[Dict[str, Any], bool]:
    """
    Run one full feedback round per poll: for each topic, run all vendors sequentially so each
    agent sees the previous agents' comments and addendums. Topics are processed in parallel.
    Returns (full state, ongoing).
    """
    _require_session(session)
    state = get_agentic_state(session)
    if not state:
        return (state or {}, False)
    if not state.get("feedback_ongoing"):
        _log("AGENTIC poll step: early return (feedback_ongoing false)")
        return (state, False)

    cursors = state.get("topic_cursors") or {}
    entry_summary = {t: ((cursors.get(t) or {}).get("round", 1), (cursors.get(t) or {}).get("vendor_index", 0), len((cursors.get(t) or {}).get("vendor_order") or [])) for t in AGENTIC_TOPIC_KEYS}
    _log(f"AGENTIC poll step: entry feedback_ongoing=True per_topic(round,vi,order_len)={entry_summary}")

    draft_letter = state.get("draft_letter") or ""
    draft_vendor = state.get("draft_vendor") or ""
    threads = state.get("threads") or _empty_threads()
    top_docs = cast(List[TopDocument], state.get("top_docs") or [])
    company_report = state.get("company_report") or ""
    job_text = state.get("job_text") or ""
    cv_text = state.get("cv_text") or ""
    metadata = state.get("metadata") or {}
    style_instructions = state.get("style_instructions") or get_style_instructions()
    additional_user_info = get_effective_additional_user_info(
        metadata, ModelVendor(draft_vendor), _user_id(session)
    )
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
        initial_vote_comment_ids = [str(c.get("id")) for c in prior_comments if c.get("id")]
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
                    "topic": bucket.get("topic"),
                    "round": bucket.get("round"),
                }
            thread_copy.append(nc)
        seed_thread_with_prior_topic_comments(thread_copy, prior_comments)
        work.append((topic, context, thread_copy, order, trace_dir, prior_comments_text, round_num, initial_vote_comment_ids))

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
            executor.submit(
                _run_one_topic_sequential,
                t,
                c,
                th,
                order,
                trace_dir,
                prior_text,
                None,
                round_num,
                initial_vote_ids,
            ): t
            for (t, c, th, order, trace_dir, prior_text, round_num, initial_vote_ids) in work
        }
        # Collect all results first before merging, so we can process in AGENTIC_TOPIC_KEYS
        # order. This prevents a race condition where a dependent topic (e.g. user_fit)
        # finishes before its source topic (e.g. precision) and correctly merges votes back
        # into threads["precision"], only for precision's result to then overwrite that with
        # its thread_copy (which never saw user_fit's votes).
        completed: Dict[str, List[Dict]] = {}
        for fut in as_completed(futures):
            topic, updated_thread, _ = fut.result()
            completed[topic] = updated_thread
        for topic in AGENTIC_TOPIC_KEYS:
            if topic not in completed:
                continue
            threads[topic] = merge_carryover_updates_and_strip(completed[topic], threads)
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


def run_agentic_refine(
    session,
    threads_override: Optional[Dict[str, List[Dict]]] = None,
    refine_sample_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Collect all positive-vote comments and addendums, then produce one final letter per vendor.
    For each vendor, draft examples are sampled proportional to votes (with same-vendor bias)
    and included in the rewrite prompt so the rewriter can draw from the best drafts.
    Count defaults to AGENTIC_REFINE_SAMPLE_COUNT or 2; API may override.
    Allow when status is feedback_done OR when feedback has stopped (feedback_ongoing false).
    If threads_override is provided, use it instead of state threads (e.g. user-edited).
    """
    _require_session(session)
    state = get_agentic_state(session)
    if not state:
        raise ValueError("Agentic state missing")
    if normalize_agentic_feedback_if_rounds_exhausted(state):
        save_agentic_state(session, state)
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
    state_threads = state.get("threads") or _empty_threads()

    def _thread_comment_count(tmap: Any) -> int:
        if not isinstance(tmap, dict):
            return 0
        total = 0
        for topic in AGENTIC_TOPIC_KEYS:
            vals = tmap.get(topic)
            if isinstance(vals, list):
                total += len(vals)
        return total

    if threads_override is not None:
        override_count = _thread_comment_count(threads_override)
        state_count = _thread_comment_count(state_threads)
        # Guard against accidental empty override from the UI completion race.
        if override_count == 0 and state_count > 0:
            _log(
                f"AGENTIC refine: ignoring empty threads_override; keeping state threads ({state_count} comments)"
            )
            threads = state_threads
        else:
            threads = threads_override
            state["threads"] = threads
    else:
        threads = state_threads

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
    sample_n = _default_refine_sample_n() if refine_sample_count is None else max(1, min(20, int(refine_sample_count)))
    refine_samples: Dict[str, List[str]] = {}
    vendor_errors: Dict[str, str] = dict(state.get("vendor_errors") or {})

    # Pre-compute per-vendor prompts (cheap, no I/O) before launching threads.
    refine_tasks: Dict[str, Tuple[str, str]] = {}  # vendor -> (d_letter, instruction_fb)
    for vendor, d_letter in draft_letters.items():
        if not d_letter.strip() or not combined.strip():
            final_letters_dict[vendor] = d_letter
            continue
        if draft_votes and len(draft_letters) > 1:
            sampled_vendors = _sample_drafts_for_vendor(
                draft_letters, draft_votes, vendor, num_agents, n=sample_n
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
        refine_tasks[vendor] = (d_letter, instruction_fb)

    def _one_refine(vendor: str) -> Tuple[str, str, float]:
        d_letter, instruction_fb = refine_tasks[vendor]
        ai_client = get_client(ModelVendor(vendor))
        letter = rewrite_letter(
            d_letter,
            instruction_fb, "NO COMMENT", "NO COMMENT",
            "NO COMMENT", "NO COMMENT", "NO COMMENT",
            ai_client, trace_dir,
            letter_plan="",
            style_instructions="",
        )
        cost_inc = getattr(ai_client, "total_cost", 0.0) or 0.0
        return vendor, letter, cost_inc

    with ThreadPoolExecutor(max_workers=len(refine_tasks) or 1) as executor:
        futures = {executor.submit(_one_refine, v): v for v in refine_tasks}
        for fut in as_completed(futures):
            vendor = futures[fut]
            try:
                vendor, final_letter, cost_inc = fut.result()
                final_letters_dict[vendor] = final_letter
                total_cost += cost_inc
                if cost_inc > 0:
                    track_api_cost(user_id, "refine", vendor, cost_inc)
            except Exception as exc:
                logger.exception("AGENTIC refine error vendor=%s: %s", vendor, exc)
                vendor_errors[vendor] = f"Refine failed: {exc}"
                # Fall back to the unrefined draft so the vendor slot is still populated.
                final_letters_dict[vendor] = refine_tasks[vendor][0]

    first_v = list(final_letters_dict.keys())[0] if final_letters_dict else draft_vendor
    state["final_letters"] = final_letters_dict
    state["final_letter"] = final_letters_dict.get(first_v) or final_letters_dict.get(draft_vendor) or ""
    if refine_samples:
        state["refine_samples"] = refine_samples
    if vendor_errors:
        state["vendor_errors"] = vendor_errors
    state["status"] = STATUS_DONE
    state["cost"] = state.get("cost", 0) + total_cost
    save_agentic_state(session, state)
    return state
