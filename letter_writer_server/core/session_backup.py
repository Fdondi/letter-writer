"""Silent host-folder backups of reconstructable session state.

Writes under SESSION_BACKUP_DIR (default /app/session_backups, mounted from
./session_backups on the host). Failures are logged only — never raise into
the request path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
SESSION_BACKUP_DIR = Path(os.environ.get("SESSION_BACKUP_DIR", "/app/session_backups"))

# Keys that constitute reconstructable work content (heartbeat/expiry excluded).
_WORK_TOP_KEYS = (
    "job_text",
    "cv_text",
    "metadata",
    "vendors",
    "style_instructions",
    "structure_instructions",
    "selected_top_docs",
    "search_result",
    "application_event_log",
    "pending_application_event_log",
    "pending_application_log_blob_store",
    "event_log_firestore_document_id",
)

# Keys applied on restore (auth kept from the live session).
RESTORE_SESSION_KEYS = (
    "job_text",
    "cv_text",
    "metadata",
    "vendors",
    "agentic",
    "style_instructions",
    "structure_instructions",
    "selected_top_docs",
    "search_result",
    "application_event_log",
    "pending_application_event_log",
    "pending_application_log_blob_store",
    "event_log_firestore_document_id",
)

_AGENTIC_SKIP_KEYS = frozenset({"last_poll_at"})
_FINGERPRINT_CACHE: Dict[str, str] = {}
_FINGERPRINT_LOCK = Lock()
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def get_backup_dir() -> Path:
    return Path(os.environ.get("SESSION_BACKUP_DIR", str(SESSION_BACKUP_DIR)))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _agentic_for_fingerprint(agentic: Any) -> Any:
    if not isinstance(agentic, dict):
        return agentic
    return {k: v for k, v in agentic.items() if k not in _AGENTIC_SKIP_KEYS}


def work_content_fingerprint(data: Dict[str, Any]) -> str:
    """Stable hash of reconstructable session content (ignores poll/expiry noise)."""
    payload: Dict[str, Any] = {}
    for key in _WORK_TOP_KEYS:
        if key in data:
            payload[key] = data.get(key)
    if "agentic" in data:
        payload["agentic"] = _agentic_for_fingerprint(data.get("agentic"))
    # Event log: length + last event timestamp/type is enough to detect appends
    # without re-serializing huge blobs every time when only heartbeats change.
    for log_key in ("application_event_log", "pending_application_event_log"):
        log = data.get(log_key)
        if isinstance(log, list):
            last = log[-1] if log else None
            last_meta = None
            if isinstance(last, dict):
                last_meta = {
                    "type": last.get("type"),
                    "timestamp": last.get("timestamp"),
                    "source": last.get("source"),
                    "vendor": last.get("vendor"),
                }
            payload[f"_{log_key}_meta"] = {"len": len(log), "last": last_meta}
            payload.pop(log_key, None)
    encoded = json.dumps(_json_safe(payload), sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _company_display_name(data: Dict[str, Any]) -> str:
    metadata = data.get("metadata") or {}
    common = metadata.get("common") if isinstance(metadata, dict) else {}
    if isinstance(common, dict):
        name = str(common.get("company_name") or "").strip()
        if name:
            return name
    return "Unknown Company"


def _safe_company_slug(data: Dict[str, Any]) -> str:
    company = _company_display_name(data)
    slug = _SAFE_NAME_RE.sub("_", company).strip("._-") or "Unknown_Company"
    return slug[:80]


def _user_id_from_session(data: Dict[str, Any]) -> Optional[str]:
    user = data.get("user")
    if isinstance(user, dict) and user.get("id") is not None:
        return str(user["id"])
    return None


def build_backup_envelope(session_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "session_key": session_key,
        "user_id": _user_id_from_session(data),
        "company_name": _company_display_name(data),
        "session": _json_safe(dict(data)),
    }


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    serialized = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    with open(tmp_path, "wb") as f:
        f.write(serialized)
    try:
        os.replace(tmp_path, path)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(serialized)
        os.replace(tmp_path, path)


def maybe_write_session_backup(session_key: str, data: Dict[str, Any]) -> Optional[Path]:
    """Write host backup if work content changed. Returns latest path or None."""
    if not session_key or not isinstance(data, dict):
        return None
    try:
        fingerprint = work_content_fingerprint(data)
        with _FINGERPRINT_LOCK:
            if _FINGERPRINT_CACHE.get(session_key) == fingerprint:
                return None
            _FINGERPRINT_CACHE[session_key] = fingerprint

        backup_dir = get_backup_dir()
        envelope = build_backup_envelope(session_key, data)
        latest_path = backup_dir / f"{session_key}.latest.json"
        _atomic_write_json(latest_path, envelope)

        company = _safe_company_slug(data)
        short_key = session_key[:12]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stamped_path = backup_dir / f"{company}.{short_key}.{ts}.json"
        _atomic_write_json(stamped_path, envelope)
        return latest_path
    except Exception as e:
        logger.warning("session backup failed for %s: %s", session_key, e)
        return None


def resolve_backup_path(filename: str) -> Path:
    """Resolve filename strictly under the backup dir. Raises ValueError on escape."""
    if not filename or not isinstance(filename, str):
        raise ValueError("filename is required")
    name = Path(filename).name
    if name != filename or name in (".", "..") or "/" in filename or "\\" in filename:
        raise ValueError("invalid backup filename")
    backup_dir = get_backup_dir().resolve()
    path = (backup_dir / name).resolve()
    try:
        path.relative_to(backup_dir)
    except ValueError as e:
        raise ValueError("backup path escapes backup directory") from e
    if path.suffix != ".json":
        raise ValueError("backup must be a .json file")
    return path


def list_session_backups(limit: int = 100) -> List[Dict[str, Any]]:
    """List backup files newest first (by mtime)."""
    backup_dir = get_backup_dir()
    if not backup_dir.exists():
        return []
    entries: List[Tuple[float, Dict[str, Any]]] = []
    for path in backup_dir.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        try:
            stat = path.stat()
            meta: Dict[str, Any] = {
                "filename": path.name,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "session_key": None,
                "user_id": None,
                "company_name": None,
                "saved_at": None,
                "is_latest": path.name.endswith(".latest.json"),
            }
            # Best-effort peek at envelope headers without loading huge session blobs fully
            # when possible — for correctness we load JSON (sessions are already on disk).
            with open(path, "r", encoding="utf-8") as f:
                envelope = json.load(f)
            if isinstance(envelope, dict):
                meta["session_key"] = envelope.get("session_key")
                meta["user_id"] = envelope.get("user_id")
                meta["company_name"] = envelope.get("company_name")
                meta["saved_at"] = envelope.get("saved_at")
            entries.append((stat.st_mtime, meta))
        except Exception as e:
            logger.warning("skip unreadable backup %s: %s", path, e)
    entries.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in entries[: max(1, limit)]]


def load_backup_envelope(filename: str) -> Dict[str, Any]:
    path = resolve_backup_path(filename)
    if not path.exists():
        raise FileNotFoundError(f"backup not found: {filename}")
    with open(path, "r", encoding="utf-8") as f:
        envelope = json.load(f)
    if not isinstance(envelope, dict):
        raise ValueError("backup root must be a JSON object")
    session = envelope.get("session")
    if not isinstance(session, dict):
        raise ValueError("backup missing session object")
    return envelope


def apply_backup_to_session_dict(
    live_session: Dict[str, Any],
    envelope: Dict[str, Any],
    current_user_id: Optional[str],
) -> Dict[str, Any]:
    """Merge backup work keys into live session; preserve live auth.

    Raises ValueError on user mismatch when backup has a user_id.
    Returns the session_state dict suitable for the API response (full vendors).
    """
    backup_user = envelope.get("user_id")
    if backup_user is not None and current_user_id is not None:
        if str(backup_user) != str(current_user_id):
            raise ValueError(
                f"backup belongs to a different user (backup user_id={backup_user})"
            )

    preserved_user = live_session.get("user")
    preserved_auth_time = live_session.get("auth_time")

    session_payload = envelope.get("session")
    if not isinstance(session_payload, dict):
        raise ValueError("backup missing session object")

    for key in RESTORE_SESSION_KEYS:
        if key in session_payload:
            live_session[key] = session_payload[key]
        elif key in live_session:
            # Explicit absence in backup clears leftover work state for that key
            # only for core reconstructable keys that should not leak across restores.
            if key in ("vendors", "agentic", "application_event_log", "pending_application_event_log"):
                live_session.pop(key, None)

    if preserved_user is not None:
        live_session["user"] = preserved_user
    if preserved_auth_time is not None:
        live_session["auth_time"] = preserved_auth_time

    # Response state: full reconstructable view (include letter_plan).
    state = {k: live_session.get(k) for k in RESTORE_SESSION_KEYS if k in live_session}
    if "metadata" in live_session:
        state["metadata"] = live_session.get("metadata")
    return state


def clear_fingerprint_cache(session_key: Optional[str] = None) -> None:
    """Test helper: clear fingerprint cache."""
    with _FINGERPRINT_LOCK:
        if session_key is None:
            _FINGERPRINT_CACHE.clear()
        else:
            _FINGERPRINT_CACHE.pop(session_key, None)
