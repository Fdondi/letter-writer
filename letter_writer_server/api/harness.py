"""Harness-only routes: list/load synthetic session fixtures."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from letter_writer.session_store import set_current_request
from letter_writer_server.core.harness import (
    harness_info,
    list_fixture_catalog,
    load_fixture_envelope,
    require_harness_mode,
)
from letter_writer_server.core.session import Session, get_session
from letter_writer_server.core.session_backup import apply_backup_to_session_dict

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/info/")
def get_harness_info():
    require_harness_mode()
    return harness_info()


@router.get("/fixtures/")
def get_harness_fixtures():
    require_harness_mode()
    return {"status": "ok", "fixtures": list_fixture_catalog()}


@router.post("/load/{fixture_id}")
def load_harness_fixture(
    fixture_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    require_harness_mode()
    set_current_request(request)
    try:
        envelope = load_fixture_envelope(fixture_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Fixture not found: {fixture_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = session.get("user") or {}
    current_user_id = str(user["id"]) if isinstance(user, dict) and user.get("id") is not None else None
    try:
        session_state = apply_backup_to_session_dict(session, envelope, current_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for key in list(session_state.keys()):
        if key in session:
            session[key] = session[key]

    response_state = dict(session_state)
    response_state.pop("cv_text", None)
    return {
        "status": "ok",
        "fixture_id": fixture_id,
        "synthetic": True,
        "session_id": session.session_key,
        "session_state": response_state,
        "stage": envelope.get("stage"),
    }
