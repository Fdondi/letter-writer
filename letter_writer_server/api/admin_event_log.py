"""Admin-only HTTP API for inspecting persisted ``application_event_log`` rows.

Protected by ``ADMIN_EVENT_LOG_API_KEY``; send header ``X-Admin-Event-Log-Key``.
When the environment variable is unset or empty, endpoints respond with 503.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from letter_writer.firestore_store import get_collection, get_document_by_id_admin

router = APIRouter()


def _admin_key_configured() -> str:
    return (os.environ.get("ADMIN_EVENT_LOG_API_KEY") or "").strip()


async def require_admin_event_log_key(
    x_admin_event_log_key: Optional[str] = Header(None, alias="X-Admin-Event-Log-Key"),
) -> None:
    expected = _admin_key_configured()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin event log API is disabled: ADMIN_EVENT_LOG_API_KEY is not set on the server.",
        )
    if not x_admin_event_log_key or x_admin_event_log_key != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-Admin-Event-Log-Key header.",
        )


def _json_friendly(obj: Any) -> Any:
    """Recursively normalize values so FastAPI/Starlette can JSON-encode responses."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            return obj.replace(tzinfo=timezone.utc).isoformat()
        return obj.astimezone(timezone.utc).isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_friendly(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_friendly(v) for v in obj]
    return str(obj)


class AdminEventLogDocumentResponse(BaseModel):
    document_id: str
    user_id: Optional[str] = None
    company_name: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    event_count: int
    application_event_log: List[Dict[str, Any]]


@router.get(
    "/document/{document_id}",
    response_model=AdminEventLogDocumentResponse,
    dependencies=[Depends(require_admin_event_log_key)],
)
async def read_document_event_log(document_id: str) -> AdminEventLogDocumentResponse:
    """Return document metadata and the full ``application_event_log`` list."""
    collection = get_collection()
    doc = get_document_by_id_admin(collection, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    raw_log = doc.get("application_event_log")
    if raw_log is None:
        log: List[Dict[str, Any]] = []
    elif isinstance(raw_log, list):
        normalized = _json_friendly(raw_log)
        if not isinstance(normalized, list):
            raise HTTPException(
                status_code=500,
                detail="application_event_log normalized to a non-list; refuse to return ambiguous data.",
            )
        log = [x for x in normalized if isinstance(x, dict)]
        if len(log) != len(normalized):
            raise HTTPException(
                status_code=500,
                detail="application_event_log contains non-object entries; refuse to return ambiguous data.",
            )
    else:
        raise HTTPException(
            status_code=500,
            detail="application_event_log is not a list; stored data is invalid.",
        )
    return AdminEventLogDocumentResponse(
        document_id=str(doc.get("id") or document_id),
        user_id=doc.get("user_id"),
        company_name=doc.get("company_name"),
        role=doc.get("role"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
        event_count=len(log),
        application_event_log=log,
    )
