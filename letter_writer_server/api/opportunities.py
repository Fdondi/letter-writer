"""``/api/opportunities``: triage alert proposals, attach postings, open drafted letters.

OPPORTUNITY_PIPELINE_PLAN.md §4.6. The desktop batch writes the drafts; these endpoints move jobs
between the states the user owns and load a ready job into the cookie session, like a restore.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from letter_writer import opportunity_store as ops
from letter_writer.firestore_store import get_user_data
from letter_writer.headless import latest_cv_text
from letter_writer.session_store import log_user_input_event, set_current_request
from letter_writer_server.core.harness import get_fixtures_dir, is_harness_mode
from letter_writer_server.core.session import Session, get_session, require_auth
from letter_writer_server.core.session_backup import apply_backup_to_session_dict

router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)

# Session key naming the opportunity the open letter came from; saving the letter marks it done.
SESSION_OPPORTUNITY_KEY = "opportunity_id"

_store: Optional[ops.OpportunityStore] = None
_harness_store: Optional["HarnessOpportunityStore"] = None


class HarnessOpportunityStore:
    """UI harness (no Firestore): the synthetic jobs in ``ui-harness/fixtures/opportunities/``,
    read-only. Every job belongs to whoever is signed in."""

    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self._items = {o["id"]: o for o in data.get("opportunities") or []}
        self._states = data.get("states") or {}

    def list_for_user(self, user_id: str, statuses=None) -> List[Dict[str, Any]]:
        return [{**o, "user_id": user_id} for o in self._items.values() if not statuses or o.get("status") in statuses]

    def get(self, opp_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        item = self._items.get(opp_id)
        return {**item, "user_id": user_id or item.get("user_id")} if item else None

    def load_state(self, opp_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._states.get(opp_id)

    def find_by_key(self, user_id: str, key: str) -> Optional[Dict[str, Any]]:
        return None

    def set_status(self, *args, **kwargs):
        raise ops.TransitionError("Harness: jobs are read-only")

    def capture(self, *args, **kwargs):
        raise ValueError("Harness: jobs are read-only")

    attach_capture = capture


def get_store() -> ops.OpportunityStore:
    """Process-wide store; tests override this dependency. The UI harness gets fixture jobs."""
    global _store, _harness_store
    if is_harness_mode():
        if _harness_store is None:
            _harness_store = HarnessOpportunityStore(get_fixtures_dir() / "opportunities" / "opportunities.json")
        return _harness_store  # type: ignore[return-value]
    if _store is None:
        _store = ops.OpportunityStore()
    return _store


def _user_id(session: Session) -> str:
    user = session.get("user") or {}
    uid = user.get("id") if isinstance(user, dict) else None
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(uid)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def serialize(opp: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    """An opportunity for the browser. Lists omit the captured text and HTML (``has_capture``
    says whether there is one); ``full`` includes the text, never the HTML or the lease."""
    out = {k: v for k, v in opp.items() if k not in ("capture", "lease")}
    capture = opp.get("capture") or {}
    out["has_capture"] = bool(str(capture.get("text") or "").strip())
    out["capture_via"] = capture.get("via") or ""
    out["captured_at"] = capture.get("captured_at")
    if full:
        out["capture_text"] = capture.get("text") or ""
    return _jsonable(out)


def _transition(store: ops.OpportunityStore, opp_id: str, user_id: str, to_state: str, from_states: List[str], fields=None):
    try:
        return store.set_status(opp_id, to_state, from_states=from_states, user_id=user_id, fields=fields)
    except KeyError:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    except ops.OwnershipError:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    except ops.TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


class SkipRequest(BaseModel):
    reason: Optional[str] = ""


class ManualRequest(BaseModel):
    url: Optional[str] = ""
    title: Optional[str] = ""
    company: Optional[str] = ""
    text: Optional[str] = ""
    vendors: Optional[List[str]] = None


class CaptureRequest(BaseModel):
    text: Optional[str] = ""
    html: Optional[str] = ""
    url: Optional[str] = ""


class DoneRequest(BaseModel):
    document_id: Optional[str] = ""


@router.get("/")
def list_opportunities(status: Optional[str] = None, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()] or None
    items = store.list_for_user(_user_id(session), statuses)
    return {"status": "ok", "opportunities": [serialize(o) for o in items]}


@router.get("/{opp_id}/")
def get_opportunity(opp_id: str, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    try:
        opp = store.get(opp_id, _user_id(session))
    except ops.OwnershipError:
        opp = None
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return {"status": "ok", "opportunity": serialize(opp, full=True)}


@router.post("/{opp_id}/approve/")
def approve(opp_id: str, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    opp = _transition(store, opp_id, _user_id(session), ops.APPROVED, [ops.PROPOSED, ops.SKIPPED], {"skip_reason": None})
    return {"status": "ok", "opportunity": serialize(opp)}


@router.post("/{opp_id}/skip/")
def skip(opp_id: str, data: SkipRequest, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    reason = (data.reason or "").strip()[:500]
    opp = _transition(
        store,
        opp_id,
        _user_id(session),
        ops.SKIPPED,
        [ops.PROPOSED, ops.APPROVED, ops.CAPTURED, ops.FAILED, ops.READY],
        {"skip_reason": reason or None},
    )
    return {"status": "ok", "opportunity": serialize(opp)}


@router.post("/{opp_id}/unskip/")
def unskip(opp_id: str, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    opp = _transition(store, opp_id, _user_id(session), ops.PROPOSED, [ops.SKIPPED], {"skip_reason": None})
    return {"status": "ok", "opportunity": serialize(opp)}


@router.post("/{opp_id}/retry/")
def retry(opp_id: str, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    opp = _transition(store, opp_id, _user_id(session), ops.CAPTURED, [ops.FAILED, ops.READY], {"vendors_failed": {}})
    return {"status": "ok", "opportunity": serialize(opp)}


@router.post("/manual/")
def add_manual(data: ManualRequest, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    try:
        opp_id, status, message = store.capture(
            _user_id(session),
            url=data.url or "",
            text=data.text or "",
            via="manual",
            title=data.title or "",
            company=data.company or "",
            vendors_requested=data.vendors,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "id": opp_id, "opportunity_status": status, "message": message}


@router.post("/{opp_id}/capture/")
def attach_capture(opp_id: str, data: CaptureRequest, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    try:
        status, message = store.attach_capture(opp_id, _user_id(session), text=data.text or "", via="share_text", html=data.html or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (KeyError, ops.OwnershipError):
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return {"status": "ok", "id": opp_id, "opportunity_status": status, "message": message}


@router.post("/{opp_id}/open/")
def open_opportunity(opp_id: str, request: Request, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    """Load the drafted session into the cookie session (like a backup restore) and return it,
    without ``cv_text``."""
    set_current_request(request)
    user_id = _user_id(session)
    try:
        opp = store.get(opp_id, user_id)
    except ops.OwnershipError:
        opp = None
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    state = store.load_state(opp_id, user_id)
    if not state:
        raise HTTPException(status_code=409, detail=f"No drafts yet: this job is '{opp.get('status')}'.")
    log_user_input_event("opportunities.open", {"opportunity_id": opp_id})
    envelope = {"user_id": opp.get("user_id"), "session": {k: v for k, v in state.items() if k != "cv_text"}}
    try:
        session_state = apply_backup_to_session_dict(session, envelope, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not session.get("cv_text"):
        cv = latest_cv_text(get_user_data(user_id, use_cache=True) or {})
        if cv:
            session["cv_text"] = cv
    session[SESSION_OPPORTUNITY_KEY] = opp_id
    # Mark restored keys dirty so the session middleware persists them.
    for key in list(session_state.keys()):
        if key in session:
            session[key] = session[key]
    response_state = {k: v for k, v in session_state.items() if k != "cv_text"}
    return {
        "status": "ok",
        "session_id": session.session_key,
        "opportunity": serialize(opp),
        "session_state": response_state,
    }


@router.post("/{opp_id}/done/")
def mark_done(opp_id: str, data: DoneRequest, session: Session = Depends(get_session), store: ops.OpportunityStore = Depends(get_store)):
    from_states = [s for s in ops.STATUSES if s not in (ops.DRAFTING, ops.DONE, ops.APPLIED)]
    fields = {"document_id": (data.document_id or "").strip() or None}
    opp = _transition(store, opp_id, _user_id(session), ops.DONE, from_states, fields)
    if session.get(SESSION_OPPORTUNITY_KEY) == opp_id:
        session.pop(SESSION_OPPORTUNITY_KEY, None)
    return {"status": "ok", "opportunity": serialize(opp)}


def finish_session_opportunity(session: Session, user_id: str, document_id: str) -> Dict[str, Any]:
    """After a letter is saved: when it came from an opened opportunity, link the document and
    mark the job done. Returns fields to merge into the save response (never raises)."""
    opp_id = session.get(SESSION_OPPORTUNITY_KEY)
    if not opp_id or not document_id:
        return {}
    from_states = [s for s in ops.STATUSES if s not in (ops.DRAFTING, ops.DONE, ops.APPLIED)]
    try:
        get_store().set_status(str(opp_id), ops.DONE, from_states=from_states, user_id=user_id, fields={"document_id": document_id})
    except ops.TransitionError:
        # Already done (an earlier save) or applied: nothing to report.
        session.pop(SESSION_OPPORTUNITY_KEY, None)
        return {"opportunity_id": opp_id}
    except Exception as exc:
        logger.warning("could not mark opportunity %s done: %s", opp_id, exc)
        return {"opportunity_warning": f"Letter saved, but the job could not be marked done: {exc}"}
    session.pop(SESSION_OPPORTUNITY_KEY, None)
    return {"opportunity_id": opp_id}
