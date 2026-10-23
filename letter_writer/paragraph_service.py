"""Paragraph flow: a few unplanned drafts compared paragraph by paragraph.

Each call is independent (the web page drives the flow): draft a whole letter,
regenerate one paragraph, continue the assembled letter with one more paragraph,
or run a single feedback topic. Feedback is advisory only; nothing here gates
the next step.

Every call returns ``usage`` (cost and tokens per cost phase) and ``timing``
(wall-clock start, total and per-stage milliseconds) so the page can keep a
timeline of what each request cost and where its time went.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .client import get_client
from .clients.base import BaseClient, ModelVendor
from .feedback_checks import PHASED_FEEDBACK_TOPIC_KEYS, run_feedback_topic
from .feedback_review import review_feedback_topic
from .laya_judge import annotate_feedback_validity
from .letter_generation import (
    continue_letter_paragraph,
    generate_letter,
    regenerate_paragraph,
    split_letter_paragraphs,
)
from .phased_service import (
    DraftInputs,
    SessionState,
    VendorPhaseState,
    _bind_user_model_overrides,
    _phase_model_role_for_call,
    _reset_client_counters,
    _update_cost,
    get_metadata_field,
    resolve_draft_inputs,
)
from .quote_span import attach_quote_spans_to_feedback
from .retrieval import select_top_documents

logger = logging.getLogger(__name__)

PARAGRAPH_FEEDBACK_TOPICS: Tuple[str, ...] = PHASED_FEEDBACK_TOPIC_KEYS


class Timeline:
    """Wall-clock profile of one request: start time, total and per-stage milliseconds."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self._t0 = time.perf_counter()
        self.stages: Dict[str, float] = {}
        self.notes: Dict[str, Any] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round(self.stages.get(name, 0.0) + (time.perf_counter() - t) * 1000, 1)

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "started_at_ms": int(self.started_at * 1000),
            "total_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "stages": dict(self.stages),
        }
        if self.notes:
            out.update(self.notes)
        return out


Usage = Dict[str, Dict[str, Any]]


def _start() -> Tuple[Timeline, Usage]:
    return Timeline(), {}


def _load_session(session_id: str) -> SessionState:
    from .session_store import load_session

    session = load_session(session_id, force_reload=True)
    if session is None:
        raise ValueError(f"Session {session_id} not found")
    return session


def _vendor_state(
    session: SessionState,
    vendor: ModelVendor,
    client: BaseClient,
    user_id: Optional[str],
    *,
    retrieve_examples: bool,
) -> Tuple[VendorPhaseState, Optional[Dict[str, Any]]]:
    """Existing vendor state, or a fresh one with example letters picked like advance_to_draft.

    Feedback calls pass ``retrieve_examples=False`` so seven parallel checks never each pay
    for a rerank when the session has no intake-selected examples. The second value is the
    rerank's usage when one ran (already tracked under the "background" cost phase).
    """
    state = session.vendors.get(vendor.value)
    if state is not None:
        return state, None
    state = VendorPhaseState()
    if not retrieve_examples:
        return state, None
    usage: Optional[Dict[str, Any]] = None
    if not getattr(session, "selected_top_docs", None) and getattr(session, "search_result", None):
        company_name = get_metadata_field(session.metadata, vendor, "company_name", "Unknown Company")
        trace_dir = Path("trace", f"{company_name}.{vendor.value}.paragraph")
        trace_dir.mkdir(parents=True, exist_ok=True)
        try:
            _reset_client_counters(client)
            state.top_docs = select_top_documents(session.search_result, session.job_text, client, trace_dir)["top_docs"]
            usage = _usage_of(client)
            _update_cost(state, client, phase="background", user_id=user_id, vendor_str=vendor.value)
        except Exception:
            logger.exception("paragraph flow: example retrieval failed for %s", vendor.value)
            state.top_docs = []
        from .session_store import save_vendor_data

        session.vendors[vendor.value] = state
        save_vendor_data(session.session_id, vendor.value, state)
    return state, usage


def _prepare(
    session_id: str,
    vendor: ModelVendor,
    user_id: Optional[str],
    company_report_override: Optional[str],
    timeline: Timeline,
    usage: Dict[str, Dict[str, Any]],
    *,
    retrieve_examples: bool = True,
) -> Tuple[BaseClient, DraftInputs]:
    with timeline.stage("prepare"):
        _bind_user_model_overrides(user_id)
        session = _load_session(session_id)
        client = get_client(vendor)
        state, examples_usage = _vendor_state(session, vendor, client, user_id, retrieve_examples=retrieve_examples)
        inputs = resolve_draft_inputs(
            session,
            state,
            vendor,
            user_id,
            company_report_override=company_report_override,
        )
    if examples_usage is not None:
        usage["background"] = examples_usage
    _reset_client_counters(client)
    return client, inputs


def _usage_of(client: BaseClient) -> Dict[str, Any]:
    return {
        "cost": float(getattr(client, "total_cost", 0.0) or 0.0),
        "input_tokens": int(getattr(client, "total_input_tokens", 0) or 0),
        "output_tokens": int(getattr(client, "total_output_tokens", 0) or 0),
        "cached_tokens": int(getattr(client, "total_cached_tokens", 0) or 0),
    }


def _capture_usage(
    usage: Dict[str, Dict[str, Any]],
    client: BaseClient,
    phase: str,
    user_id: Optional[str],
    vendor: ModelVendor,
) -> None:
    """Record the client's counters under ``phase`` (tracked for spending), then reset them."""
    usage[phase] = _usage_of(client)
    scratch = VendorPhaseState()
    _update_cost(scratch, client, phase=phase, user_id=user_id, vendor_str=vendor.value)
    _reset_client_counters(client)


def _accounting(usage: Dict[str, Dict[str, Any]], timeline: Timeline) -> Dict[str, Any]:
    return {
        "cost": sum(float(u.get("cost") or 0.0) for u in usage.values()),
        "usage": usage,
        "timing": timeline.as_dict(),
    }


def _model_label(model_role: Any) -> str:
    return model_role if isinstance(model_role, str) else getattr(model_role, "value", str(model_role))


def _paragraph_rows(texts: Sequence[str]) -> List[Dict[str, str]]:
    return [{"id": str(uuid.uuid4()), "text": t} for t in texts]


def draft_letter_for_paragraphs(
    *,
    session_id: str,
    vendor: ModelVendor,
    user_id: Optional[str],
    company_report_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Whole letter, no plan step, split into paragraphs."""
    timeline, usage = _start()
    client, inp = _prepare(session_id, vendor, user_id, company_report_override, timeline, usage)
    model_role = _phase_model_role_for_call(vendor, "paragraph", user_id)
    trace_dir = Path("trace", f"paragraph.{vendor.value}.draft")
    trace_dir.mkdir(parents=True, exist_ok=True)
    with timeline.stage("llm"):
        letter, known_weaknesses = generate_letter(
            inp.cv_text,
            inp.top_docs,
            inp.company_report,
            inp.job_text,
            client,
            trace_dir,
            inp.style_instructions,
            inp.additional_user_info,
            letter_plan="",
            hire_problem=inp.hire_problem,
            language_prefix=inp.language_prefix,
            model_role=model_role,
        )
    _capture_usage(usage, client, "paragraph_draft", user_id, vendor)
    return {
        "draft_id": str(uuid.uuid4()),
        "vendor": vendor.value,
        "model": _model_label(model_role),
        "letter": letter,
        "paragraphs": _paragraph_rows(split_letter_paragraphs(letter)),
        "known_weaknesses": known_weaknesses,
        **_accounting(usage, timeline),
    }


def format_regenerate_feedback(user_feedback: str, ai_notes: Sequence[Dict[str, Any]]) -> str:
    """User text first, then any AI notes the user ticked."""
    parts: List[str] = []
    if (user_feedback or "").strip():
        parts.append(user_feedback.strip())
    for note in ai_notes or []:
        obs = str(note.get("observation") or "").strip()
        if not obs:
            continue
        topic = str(note.get("topic") or "").strip()
        quote = str(note.get("quote") or "").strip()
        line = f"- [{topic}] {obs}" if topic else f"- {obs}"
        if quote:
            line += f' (about: "{quote}")'
        parts.append(line)
    return "\n".join(parts)


def regenerate_letter_paragraph(
    *,
    session_id: str,
    vendor: ModelVendor,
    user_id: Optional[str],
    paragraphs: Sequence[str],
    index: int,
    user_feedback: str = "",
    ai_notes: Sequence[Dict[str, Any]] = (),
    company_report_override: Optional[str] = None,
) -> Dict[str, Any]:
    timeline, usage = _start()
    client, inp = _prepare(session_id, vendor, user_id, company_report_override, timeline, usage)
    model_role = _phase_model_role_for_call(vendor, "paragraph", user_id)
    with timeline.stage("llm"):
        text = regenerate_paragraph(
            list(paragraphs),
            index,
            format_regenerate_feedback(user_feedback, ai_notes),
            inp.cv_text,
            inp.top_docs,
            inp.company_report,
            inp.job_text,
            client,
            style_instructions=inp.style_instructions,
            additional_user_info=inp.additional_user_info,
            hire_problem=inp.hire_problem,
            language_prefix=inp.language_prefix,
            model_role=model_role,
        )
    _capture_usage(usage, client, "paragraph_regen", user_id, vendor)
    return {
        "paragraph": {"id": str(uuid.uuid4()), "text": text},
        "vendor": vendor.value,
        "model": _model_label(model_role),
        **_accounting(usage, timeline),
    }


def continue_assembled_letter(
    *,
    session_id: str,
    vendor: ModelVendor,
    user_id: Optional[str],
    letter_so_far: str,
    instructions: str = "",
    company_report_override: Optional[str] = None,
) -> Dict[str, Any]:
    timeline, usage = _start()
    client, inp = _prepare(session_id, vendor, user_id, company_report_override, timeline, usage)
    model_role = _phase_model_role_for_call(vendor, "paragraph", user_id)
    with timeline.stage("llm"):
        text, complete = continue_letter_paragraph(
            letter_so_far,
            inp.cv_text,
            inp.top_docs,
            inp.company_report,
            inp.job_text,
            client,
            instructions=instructions,
            style_instructions=inp.style_instructions,
            additional_user_info=inp.additional_user_info,
            hire_problem=inp.hire_problem,
            language_prefix=inp.language_prefix,
            model_role=model_role,
        )
    _capture_usage(usage, client, "paragraph_continue", user_id, vendor)
    return {
        "paragraph": {"id": str(uuid.uuid4()), "text": text},
        "letter_complete": complete,
        "vendor": vendor.value,
        "model": _model_label(model_role),
        **_accounting(usage, timeline),
    }


def filter_items_to_focus(
    items: Sequence[Dict[str, Any]],
    focus_start: Optional[int],
    focus_end: Optional[int],
) -> List[Dict[str, Any]]:
    """Keep items quoting inside [focus_start, focus_end); unanchored items become whole-letter notes."""
    if focus_start is None or focus_end is None:
        return list(items)
    out: List[Dict[str, Any]] = []
    for it in items:
        start, end = it.get("span_start"), it.get("span_end")
        if not isinstance(start, int) or not isinstance(end, int):
            out.append({**it, "whole_letter": True})
            continue
        if start < focus_end and end > focus_start:
            out.append(it)
    return out


def paragraph_feedback_topic(
    *,
    session_id: str,
    vendor: ModelVendor,
    user_id: Optional[str],
    topic: str,
    letter_text: str,
    focus_start: Optional[int] = None,
    focus_end: Optional[int] = None,
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
    company_report_override: Optional[str] = None,
) -> Dict[str, Any]:
    """One feedback check on the whole letter, optionally narrowed to one paragraph.

    Same post-processing as the vendor flow, per topic so results still stream:
    quote spans, focus filter, Laya grounding verdicts (ungrounded fixes stay on the
    item and are drawn faint), then the LLM keep/drop review. Dropped items are
    returned separately for study and not shown.
    """
    if topic not in PARAGRAPH_FEEDBACK_TOPICS:
        raise KeyError(f"Unknown feedback topic: {topic}")
    timeline, usage = _start()
    client, inp = _prepare(
        session_id, vendor, user_id, company_report_override, timeline, usage, retrieve_examples=False
    )
    with timeline.stage("check"):
        raw_items = run_feedback_topic(
            topic,
            draft_letter=letter_text,
            cv_text=inp.cv_text,
            company_report=inp.company_report,
            job_text=inp.job_text,
            top_docs=inp.top_docs,
            client=client,
            style_instructions=inp.style_instructions,
            additional_user_info=inp.additional_user_info,
            hire_problem=inp.hire_problem,
            known_weaknesses=known_weaknesses,
            annotate=False,
        )
    _capture_usage(usage, client, "paragraph_feedback", user_id, vendor)

    with timeline.stage("quote_spans"):
        try:
            attach_quote_spans_to_feedback({topic: raw_items}, letter_text)
        except Exception:
            logger.exception("paragraph feedback: attaching quote spans failed (%s)", topic)
    items = filter_items_to_focus(raw_items, focus_start, focus_end)

    with timeline.stage("laya"):
        try:
            laya = annotate_feedback_validity({topic: items}, letter_text)
            timeline.notes["laya_available"] = bool(laya.get("available"))
        except Exception as e:
            logger.exception("paragraph feedback: Laya scoring failed (%s)", topic)
            timeline.notes["laya_error"] = f"{type(e).__name__}: {e}"
    timeline.notes["laya_scored"] = sum(1 for it in items if it.get("laya_verdict") in ("valid", "invalid"))

    dropped: List[Dict[str, Any]] = []
    with timeline.stage("review"):
        try:
            items, dropped = review_feedback_topic(
                client=client,
                topic=topic,
                items=items,
                draft_letter=letter_text,
                style_instructions=inp.style_instructions,
                cv_text=inp.cv_text,
                additional_user_info=inp.additional_user_info,
                company_report=inp.company_report,
                job_text=inp.job_text,
                top_docs=inp.top_docs,
                hire_problem=inp.hire_problem,
                known_weaknesses=known_weaknesses,
            )
        except Exception as e:
            logger.exception("paragraph feedback: review failed (%s); showing unreviewed notes", topic)
            timeline.notes["review_error"] = f"{type(e).__name__}: {e}"
    _capture_usage(usage, client, "paragraph_feedback_review", user_id, vendor)

    return {
        "topic": topic,
        "items": items,
        "dropped_items": dropped,
        "raw_count": len(raw_items),
        **_accounting(usage, timeline),
    }
