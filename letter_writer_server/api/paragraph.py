"""Paragraph flow: few unplanned drafts, per-paragraph regenerate/continue, advisory feedback."""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from letter_writer.clients.base import ModelVendor
from letter_writer.paragraph_service import (
    PARAGRAPH_FEEDBACK_TOPICS,
    continue_assembled_letter,
    draft_letter_for_paragraphs,
    paragraph_feedback_topic,
    regenerate_letter_paragraph,
)
from letter_writer.session_store import append_application_event, log_user_input_event, set_current_request
from letter_writer_server.api.cost_utils import check_spending_limits, with_user_monthly_cost
from letter_writer_server.core.session import Session, get_session, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)

PARAGRAPH_SESSION_KEY = "paragraph"


class ParagraphDraftRequest(BaseModel):
    company_report: Optional[str] = None


class ParagraphRegenerateRequest(BaseModel):
    paragraphs: List[str]
    index: int
    user_feedback: str = ""
    ai_notes: List[Dict[str, Any]] = Field(default_factory=list)
    draft_id: Optional[str] = None
    paragraph_id: Optional[str] = None
    company_report: Optional[str] = None


class ParagraphContinueRequest(BaseModel):
    letter_so_far: str = ""
    instructions: str = ""
    company_report: Optional[str] = None


class ParagraphFeedbackRequest(BaseModel):
    letter_text: str
    focus_start: Optional[int] = None
    focus_end: Optional[int] = None
    known_weaknesses: Optional[List[Dict[str, Any]]] = None
    draft_id: Optional[str] = None
    paragraph_id: Optional[str] = None
    company_report: Optional[str] = None


class ParagraphStateRequest(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)


def _user_id(session: Session) -> str:
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return (user or {}).get("id") or "anonymous"


def _session_id(session: Session) -> str:
    if not session.session_key:
        raise HTTPException(status_code=400, detail="No active session")
    return session.session_key


def _vendor(vendor: str) -> ModelVendor:
    try:
        return ModelVendor(vendor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Unknown vendor: {vendor}") from e


def _timed(kind: str, vendor: str, ids: Dict[str, Any], call: Callable[[], Dict[str, Any]], bad_request: tuple = ()) -> Dict[str, Any]:
    """Run one LLM step and log a ``paragraph.timing`` event (cost, tokens, per-stage ms), even on failure."""
    t0 = time.perf_counter()
    started = time.time()
    try:
        out = call()
    except Exception as e:
        append_application_event(
            {
                "type": "timing",
                "source": f"paragraph.{kind}",
                "payload": {
                    **ids,
                    "vendor": vendor,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "started_at_ms": int(started * 1000),
                    "route_ms": round((time.perf_counter() - t0) * 1000, 1),
                },
            }
        )
        if isinstance(e, bad_request):
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.exception("paragraph.%s failed (vendor=%s)", kind, vendor)
        raise HTTPException(status_code=500, detail=str(e)) from e
    timing = {**(out.get("timing") or {}), "route_ms": round((time.perf_counter() - t0) * 1000, 1)}
    out["timing"] = timing
    payload: Dict[str, Any] = {
        **ids,
        "vendor": vendor,
        "model": out.get("model"),
        "ok": True,
        "cost": out.get("cost"),
        "usage": out.get("usage"),
        "timing": timing,
    }
    if kind == "feedback":
        payload.update(
            raw_count=out.get("raw_count"),
            kept_count=len(out.get("items") or []),
            dropped_items=out.get("dropped_items") or [],
        )
    append_application_event({"type": "timing", "source": f"paragraph.{kind}", "payload": payload})
    logger.info(
        "paragraph.%s vendor=%s %.0fms stages=%s cost=$%.4f",
        kind,
        vendor,
        timing["route_ms"],
        timing.get("stages"),
        float(out.get("cost") or 0.0),
    )
    return out


@router.post("/draft/{vendor}/")
def paragraph_draft(vendor: str, data: ParagraphDraftRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event("paragraph.draft", {"vendor": vendor})
    user_id = _user_id(session)
    vendor_enum = _vendor(vendor)
    session_id = _session_id(session)
    out = _timed(
        "draft",
        vendor,
        {},
        lambda: draft_letter_for_paragraphs(
            session_id=session_id,
            vendor=vendor_enum,
            user_id=user_id,
            company_report_override=data.company_report,
        ),
    )
    return with_user_monthly_cost({"status": "ok", **out}, session)


@router.post("/regenerate/{vendor}/")
def paragraph_regenerate(vendor: str, data: ParagraphRegenerateRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event(
        "paragraph.regenerate",
        {
            "vendor": vendor,
            "draft_id": data.draft_id,
            "paragraph_id": data.paragraph_id,
            "index": data.index,
            "user_feedback": data.user_feedback,
            "ai_notes": data.ai_notes,
            "previous_text": data.paragraphs[data.index] if 0 <= data.index < len(data.paragraphs) else None,
        },
    )
    user_id = _user_id(session)
    vendor_enum = _vendor(vendor)
    session_id = _session_id(session)
    out = _timed(
        "regenerate",
        vendor,
        {"draft_id": data.draft_id, "paragraph_id": data.paragraph_id},
        lambda: regenerate_letter_paragraph(
            session_id=session_id,
            vendor=vendor_enum,
            user_id=user_id,
            paragraphs=data.paragraphs,
            index=data.index,
            user_feedback=data.user_feedback,
            ai_notes=data.ai_notes,
            company_report_override=data.company_report,
        ),
        bad_request=(ValueError,),
    )
    return with_user_monthly_cost({"status": "ok", **out}, session)


@router.post("/continue/{vendor}/")
def paragraph_continue(vendor: str, data: ParagraphContinueRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    log_user_input_event(
        "paragraph.continue",
        {"vendor": vendor, "letter_so_far": data.letter_so_far, "instructions": data.instructions},
    )
    user_id = _user_id(session)
    vendor_enum = _vendor(vendor)
    session_id = _session_id(session)
    out = _timed(
        "continue",
        vendor,
        {},
        lambda: continue_assembled_letter(
            session_id=session_id,
            vendor=vendor_enum,
            user_id=user_id,
            letter_so_far=data.letter_so_far,
            instructions=data.instructions,
            company_report_override=data.company_report,
        ),
    )
    return with_user_monthly_cost({"status": "ok", **out}, session)


@router.post("/feedback/{vendor}/{topic}/")
def paragraph_feedback(vendor: str, topic: str, data: ParagraphFeedbackRequest, request: Request, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    set_current_request(request)
    if topic not in PARAGRAPH_FEEDBACK_TOPICS:
        raise HTTPException(status_code=400, detail=f"Unknown feedback topic: {topic}")
    log_user_input_event(
        "paragraph.feedback",
        {"vendor": vendor, "topic": topic, "draft_id": data.draft_id, "paragraph_id": data.paragraph_id},
    )
    user_id = _user_id(session)
    vendor_enum = _vendor(vendor)
    session_id = _session_id(session)
    out = _timed(
        "feedback",
        vendor,
        {"topic": topic, "draft_id": data.draft_id, "paragraph_id": data.paragraph_id},
        lambda: paragraph_feedback_topic(
            session_id=session_id,
            vendor=vendor_enum,
            user_id=user_id,
            topic=topic,
            letter_text=data.letter_text,
            focus_start=data.focus_start,
            focus_end=data.focus_end,
            known_weaknesses=data.known_weaknesses,
            company_report_override=data.company_report,
        ),
    )
    return with_user_monthly_cost({"status": "ok", **out}, session)


@router.get("/state/")
def paragraph_get_state(session: Session = Depends(get_session)):
    return {"status": "ok", "state": session.get(PARAGRAPH_SESSION_KEY) or {}}


@router.post("/state/")
def paragraph_save_state(data: ParagraphStateRequest, request: Request, session: Session = Depends(get_session)):
    """Persist the page state; each UI choice (use/discard/edit/feedback) goes to the event log."""
    set_current_request(request)
    for ev in data.events:
        log_user_input_event("paragraph.choice", {**ev, "received_at": time.time()})
    session[PARAGRAPH_SESSION_KEY] = data.state
    return {"status": "ok"}


@router.post("/clear/")
def paragraph_clear(request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    log_user_input_event("paragraph.clear", {})
    session.pop(PARAGRAPH_SESSION_KEY, None)
    return {"status": "ok"}
