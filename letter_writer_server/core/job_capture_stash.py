"""Filesystem stash for unauthenticated job-page captures (extension ingest)."""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
CAPTURE_TTL_SECONDS = 15 * 60
MAX_TEXT_CHARS = 200_000
MAX_HTML_CHARS = 800_000
MAX_URL_CHARS = 2000
MAX_TITLE_CHARS = 500

_STASH_DIR = Path(os.environ.get("JOB_CAPTURE_STASH_DIR", "/tmp/letter_writer_captures"))


def _stash_dir() -> Path:
    _STASH_DIR.mkdir(parents=True, exist_ok=True)
    return _STASH_DIR


def _path_for(capture_id: str) -> Path:
    return _stash_dir() / f"{capture_id}.json"


def validate_ingest_payload(data: Dict[str, Any]) -> Dict[str, str]:
    """Normalize and cap ingest fields. Raises ValueError if empty."""
    text = str(data.get("text") or "")[:MAX_TEXT_CHARS]
    html = str(data.get("html") or "")[:MAX_HTML_CHARS]
    url = str(data.get("url") or "")[:MAX_URL_CHARS]
    title = str(data.get("title") or "")[:MAX_TITLE_CHARS]
    if not text.strip() and not html.strip():
        raise ValueError("Page had no text or HTML to capture")
    return {"url": url, "title": title, "text": text, "html": html}


def store_capture(payload: Dict[str, str], ttl_seconds: int = CAPTURE_TTL_SECONDS) -> str:
    capture_id = secrets.token_urlsafe(16)
    now = time.time()
    envelope = {
        "format_version": FORMAT_VERSION,
        "saved_at": now,
        "expires_at": now + max(1, int(ttl_seconds)),
        "payload": payload,
    }
    path = _path_for(capture_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(envelope), encoding="utf-8")
    tmp.replace(path)
    return capture_id


def load_capture(capture_id: str) -> Optional[Dict[str, str]]:
    if not capture_id or "/" in capture_id or ".." in capture_id:
        return None
    path = _path_for(capture_id)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict):
        return None
    expires_at = float(envelope.get("expires_at") or 0)
    if expires_at and time.time() > expires_at:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else None


def delete_capture(capture_id: str) -> None:
    if not capture_id or "/" in capture_id or ".." in capture_id:
        return
    try:
        _path_for(capture_id).unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Failed to delete capture %s: %s", capture_id, e)
