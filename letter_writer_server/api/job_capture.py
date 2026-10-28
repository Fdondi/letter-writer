"""Browser-extension job capture: queue a page as a pipeline job, or stash it and extract into the
logged-in session."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from letter_writer import opportunity_store as ops

from letter_writer_server.api.cost_utils import check_spending_limits, with_user_monthly_cost
from letter_writer_server.api.extract_pipeline import run_capture_extract
from letter_writer_server.core.harness import apply_harness_job_capture, is_harness_mode
from letter_writer_server.core.job_capture_stash import (
    delete_capture,
    load_capture,
    store_capture,
    validate_ingest_payload,
)
from letter_writer_server.core.rate_limit import limiter
from letter_writer_server.core.session import Session, get_session, require_auth

router = APIRouter()
logger = logging.getLogger(__name__)


class IngestRequest(BaseModel):
    url: Optional[str] = ""
    title: Optional[str] = ""
    text: Optional[str] = ""
    html: Optional[str] = ""
    queue: Optional[bool] = False


class ProcessRequest(BaseModel):
    scale_config: Optional[Dict[str, Any]] = None


@router.post("/ingest/")
@limiter.limit("20/minute")
async def ingest_job_capture(request: Request, data: IngestRequest):
    """Unauthenticated stash of a captured job page. Extraction runs on /process/ after login.
    With ``queue``, the page becomes a pipeline job right away (like the phone app's capture)."""
    try:
        payload = validate_ingest_payload(data.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    owner = _capture_owner(request)
    if data.queue and owner and (payload.get("text") or "").strip() and not is_harness_mode():
        # Queue the job like the app does: the desktop batch extracts and drafts it.
        try:
            queued = await run_in_threadpool(_queue_capture, owner, payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception:
            logger.exception("[JOB-CAPTURE] queueing failed; stashing instead")
        else:
            logger.info("[JOB-CAPTURE] queued id=%s status=%s", queued["opportunity_id"], queued["opportunity_status"])
            return {"status": "ok", **queued}
    if owner and payload.get("url"):
        try:
            matched = await run_in_threadpool(_attach_to_approved_opportunity, owner, payload)
        except Exception:
            logger.exception("[JOB-CAPTURE] opportunity match failed; stashing instead")
            matched = None
        if matched:
            return {"status": "ok", **matched}

    capture_id = store_capture(payload)
    logger.info(
        "[JOB-CAPTURE] ingested id=%s text_len=%s html_len=%s",
        capture_id,
        len(payload.get("text") or ""),
        len(payload.get("html") or ""),
    )
    response: Dict[str, Any] = {"status": "ok", "capture_id": capture_id}
    if data.queue:
        response["note"] = (
            "Queueing needs the signed-in session or OPPORTUNITY_OWNER_USER_ID on the backend; "
            "the page was stashed for interactive intake instead."
        )
    return response


def _capture_owner(request: Request) -> Optional[str]:
    """Whose opportunities an unauthenticated capture may touch: the signed-in user when the
    request carries the session cookie, else ``OPPORTUNITY_OWNER_USER_ID`` (single-user host).
    None disables opportunity matching."""
    session = getattr(request.state, "session", None)
    user = session.get("user") if session is not None else None
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    return (os.environ.get("OPPORTUNITY_OWNER_USER_ID") or "").strip() or None


def _opportunity_store() -> ops.OpportunityStore:
    from letter_writer_server.api.opportunities import get_store

    return get_store()


def _queue_capture(owner: str, payload: Dict[str, str]) -> Dict[str, Any]:
    """Queue a captured page as a pipeline job with the phone's capture rules: a new job is
    ``captured`` (the next batch run drafts it), an existing one gets the text unless the desktop
    is drafting it or already did."""
    opp_id, status, message = _opportunity_store().capture(
        owner,
        url=payload.get("url") or "",
        text=payload.get("text") or "",
        html=payload.get("html") or None,
        via="extension",
        title=payload.get("title") or "",
    )
    return {"opportunity_id": opp_id, "opportunity_status": status, "message": message}


def _attach_to_approved_opportunity(owner: str, payload: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """A capture of an approved job's page becomes that job's posting (queued for the batch)."""
    store = _opportunity_store()
    try:
        opp = store.find_by_key(owner, ops.canonical_key(payload["url"]))
    except ops.OwnershipError:
        return None
    if not opp or opp.get("status") != ops.APPROVED:
        return None
    text = (payload.get("text") or "").strip()
    if not text:
        return None
    status, message = store.attach_capture(opp["id"], owner, text=text, via="extension", html=payload.get("html") or None)
    logger.info("[JOB-CAPTURE] attached capture to opportunity %s (%s)", opp["id"], status)
    return {"opportunity_id": opp["id"], "opportunity_status": status, "message": message}


@router.get("/pending/")
@limiter.limit("30/minute")
async def pending_captures(request: Request, url: Optional[str] = None):
    """Approved jobs still waiting for their posting: the extension captures these on its own when
    the user opens one. URLs and keys only; with ``url``, only the job that URL is a posting of."""
    owner = _capture_owner(request)
    if not owner:
        return {"status": "ok", "opportunities": []}
    items: List[Dict[str, Any]] = await run_in_threadpool(lambda: _opportunity_store().list_for_user(owner, [ops.APPROVED]))
    if url:
        key = ops.canonical_key(url)
        items = [o for o in items if o.get("canonical_key") == key]
    return {
        "status": "ok",
        "opportunities": [
            {"id": o["id"], "url": o.get("url") or "", "canonical_key": o.get("canonical_key") or ""}
            for o in items
            if o.get("url")
        ],
    }


@router.get("/{capture_id}/")
@limiter.limit("40/minute")
async def peek_job_capture(
    request: Request,
    capture_id: str,
    session: Session = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    """Return captured URL/title immediately; does not run extraction or consume the stash."""
    payload = load_capture(capture_id)
    if not payload:
        raise HTTPException(
            status_code=400,
            detail="Capture not found or expired. Send the page from the extension again.",
        )
    url = str(payload.get("url") or "").strip()
    title = str(payload.get("title") or "").strip()
    if url:
        metadata = dict(session.get("metadata") or {})
        common = dict(metadata.get("common") or {})
        common["source_url"] = url
        metadata["common"] = common
        session["metadata"] = metadata
    return {"status": "ok", "url": url, "title": title, "source_url": url}


@router.post("/{capture_id}/process/")
async def process_job_capture(
    capture_id: str,
    data: ProcessRequest,
    session: Session = Depends(get_session),
    _user: dict = Depends(require_auth),
    _limit: None = Depends(check_spending_limits),
):
    """Authenticated full extract from a stashed page dump."""
    payload = load_capture(capture_id)
    if not payload:
        raise HTTPException(
            status_code=400,
            detail="Capture not found or expired. Send the page from the extension again.",
        )

    visible_text = str(payload.get("text") or "")
    html = str(payload.get("html") or "")
    source_url = str(payload.get("url") or "")
    if not visible_text.strip() and not html.strip():
        delete_capture(capture_id)
        raise HTTPException(status_code=400, detail="Capture had no text or HTML")

    if is_harness_mode():
        result = apply_harness_job_capture(session, payload)
        delete_capture(capture_id)
        return result

    try:
        result = run_capture_extract(
            session,
            visible_text=visible_text,
            html=html,
            source_url=source_url,
            scale_cfg=data.scale_config,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[JOB-CAPTURE] process failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Job capture extraction failed: {e}") from e

    delete_capture(capture_id)
    return with_user_monthly_cost(
        {
            "status": "ok",
            "job_text": result["job_text"],
            "extraction": result["extraction"],
            "similar_documents": result["similar_documents"],
            "top_docs": result["top_docs"],
            "session_id": result["session_id"],
            "source_url": result["source_url"],
        },
        session,
    )
