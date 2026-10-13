"""Browser-extension job capture: stash a page, then extract into the logged-in session."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from letter_writer.client import get_extraction_client
from letter_writer.generation import extract_job_page_metadata
from letter_writer.page_templates import attach_jobs_ch_company_about, extract_from_captured_page
from letter_writer_server.api.cost_utils import check_spending_limits, with_user_monthly_cost
from letter_writer_server.api.extract_pipeline import resolve_cv_for_extract, run_extract_pipeline
from letter_writer_server.api.misc import _reset_client_counters, _track_and_reset_client_cost
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


class ProcessRequest(BaseModel):
    scale_config: Optional[Dict[str, Any]] = None


@router.post("/ingest/")
@limiter.limit("20/minute")
async def ingest_job_capture(request: Request, data: IngestRequest):
    """Unauthenticated stash of a captured job page. Extraction runs on /process/ after login."""
    try:
        payload = validate_ingest_payload(data.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    capture_id = store_capture(payload)
    logger.info(
        "[JOB-CAPTURE] ingested id=%s text_len=%s html_len=%s",
        capture_id,
        len(payload.get("text") or ""),
        len(payload.get("html") or ""),
    )
    return {"status": "ok", "capture_id": capture_id}


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

    parsed_page = extract_from_captured_page(html, source_url)
    attach_jobs_ch_company_about(parsed_page)
    focused_text = str(parsed_page.get("job_text") or "").strip()
    competence_source_text = focused_text or visible_text or html
    canonical_url = str(parsed_page.get("source_url") or "").strip() or source_url

    cv_text, user_data, user_id = resolve_cv_for_extract(session)
    extract_vendor, ai_client = get_extraction_client(user_data)
    _reset_client_counters(ai_client)
    trace_dir = Path("trace", "extraction.page_capture")

    def _page_metadata():
        meta = extract_job_page_metadata(
            visible_text,
            ai_client,
            html=html,
            source_url=source_url,
            trace_dir=trace_dir,
            parsed_page=parsed_page,
        )
        if canonical_url:
            meta["source_url"] = str(meta.get("source_url") or "").strip() or canonical_url
        return meta

    try:
        result = run_extract_pipeline(
            competence_source_text=competence_source_text,
            similar_job_text=None,
            page_metadata_fn=_page_metadata,
            session=session,
            scale_cfg=data.scale_config,
            user_data=user_data,
            cv_text=cv_text,
            user_id=user_id,
            ai_client=ai_client,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[JOB-CAPTURE] process failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Job capture extraction failed: {e}") from e

    delete_capture(capture_id)

    _track_and_reset_client_cost(
        user_id=user_id,
        phase="extract",
        vendor=extract_vendor.value,
        client=ai_client,
    )
    return with_user_monthly_cost(
        {
            "status": "ok",
            "job_text": result["job_text"],
            "extraction": result["extraction"],
            "similar_documents": result["similar_documents"],
            "top_docs": result["top_docs"],
            "session_id": result["session_id"],
            "source_url": str(
                (result.get("extraction") or {}).get("source_url") or canonical_url
            ),
        },
        session,
    )
