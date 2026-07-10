"""Unified access to letter data for dataset building.

Two sources, one output shape:

- ``backup``: a Datastore/Firestore export directory on disk (e.g. ``data_backup``),
  parsed without any cloud dependency or credentials.
- ``cloud``: the live Firestore database, read through the same client/env
  conventions the app uses for writes (``letter_writer.firestore_store``), and
  cached locally as JSON so subsequent runs are offline.

Both return normalized dicts:

    {
        "documents": [
            {"doc_id", "company_name", "role", "language", "job_text",
             "letter_text", "ai_letters": [{"vendor", "text", ...}], "created_at"},
            ...
        ],
        "feedbacks": [
            {"document_id", "vendor", "action", "original_text", "final_text",
             "user_corrections", "created_at"},
            ...
        ],
    }

``created_at`` is an ISO-8601 string (UTC) in both cases.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"
_CACHED_KINDS = ("documents", "feedbacks")

# Fields that are large or useless for training and are dropped everywhere.
_STRIP_FIELDS = {"vector", "blocks", "application_fingerprint", "autocomplete_history",
                 "autocomplete_sections", "application_event_log"}


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _iso_from_any(value: Any) -> Optional[str]:
    """Normalize export microseconds, datetimes, or ISO strings to ISO-8601 UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1e6, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        return value
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items() if k not in _STRIP_FIELDS}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return _iso_from_any(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Firestore Vector and other exotic types
    try:
        return list(value)  # type: ignore[arg-type]
    except TypeError:
        return str(value)


def _normalize_ai_letters(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "vendor": item.get("vendor") or "unknown",
            "text": text,
            "rating": item.get("rating"),
            "comment": item.get("comment") or "",
            "user_corrections": item.get("user_corrections"),
            "created_at": _iso_from_any(item.get("created_at")),
        })
    return out


def _normalize_document(ent: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    return {
        "doc_id": doc_id,
        "company_name": ent.get("company_name_original") or ent.get("company_name") or "",
        "role": ent.get("role") or "",
        "language": ent.get("language") or "",
        "job_text": ent.get("job_text") or "",
        "letter_text": ent.get("letter_text") or "",
        "negative_letter_text": ent.get("negative_letter_text") or "",
        "ai_letters": _normalize_ai_letters(ent.get("ai_letters")),
        "created_at": _iso_from_any(ent.get("created_at")),
    }


def _normalize_feedback(ent: Dict[str, Any], fb_id: str) -> Dict[str, Any]:
    return {
        "feedback_id": fb_id,
        "document_id": ent.get("document_id") or "",
        "vendor": ent.get("vendor") or "",
        "action": ent.get("action") or "",
        "original_text": ent.get("original_text") or "",
        "final_text": ent.get("final_text") or "",
        "comment": ent.get("comment") or "",
        "user_corrections": ent.get("user_corrections"),
        "created_at": _iso_from_any(ent.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Backup source
# ---------------------------------------------------------------------------

def _find_export_dir(root: Path) -> Path:
    """Accept either the export root (data_backup) or the dir with output-N files."""
    if any(p.name.startswith("output-") for p in root.iterdir()):
        return root
    candidates = sorted(root.rglob("output-0"))
    if not candidates:
        raise FileNotFoundError(f"no Datastore export output files under {root}")
    return candidates[0].parent


def load_from_backup(backup_dir: str | Path) -> Dict[str, List[Dict[str, Any]]]:
    from .datastore_export import load_export

    export_dir = _find_export_dir(Path(backup_dir))
    logger.info("loading Datastore export from %s", export_dir)
    by_kind = load_export(str(export_dir))

    def key_name(ent: Dict[str, Any]) -> str:
        kp = ent.get("__key__") or []
        if kp:
            return str(kp[-1].get("name") or kp[-1].get("id") or "")
        return ""

    documents = [
        _normalize_document(e, key_name(e)) for e in by_kind.get("documents", [])
    ]
    feedbacks = [
        _normalize_feedback(e, key_name(e)) for e in by_kind.get("feedbacks", [])
    ]
    return {"documents": documents, "feedbacks": feedbacks}


# ---------------------------------------------------------------------------
# Cloud source (with local JSON cache)
# ---------------------------------------------------------------------------

def _cache_path(cache_dir: Path, kind: str) -> Path:
    return cache_dir / f"{kind}.json"


def _fetch_cloud_kind(kind: str, user_id: Optional[str]) -> List[Dict[str, Any]]:
    """Stream one collection using the app's own Firestore client conventions."""
    from letter_writer.firestore_store import (  # lazy: cloud deps optional
        get_collection,
        get_feedbacks_collection,
    )

    if kind == "documents":
        collection = get_collection()
    elif kind == "feedbacks":
        collection = get_feedbacks_collection()
    else:
        raise ValueError(f"unsupported kind: {kind}")

    query = collection
    if user_id:
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = collection.where(filter=FieldFilter("user_id", "==", str(user_id)))

    out: List[Dict[str, Any]] = []
    for snap in query.stream():
        data = snap.to_dict() or {}
        data = _json_safe(data)
        data["__id__"] = snap.id
        out.append(data)
    return out


def load_from_cloud(
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
    user_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Read documents and feedbacks from Firestore, caching raw JSON locally.

    The cache under ``cache_dir`` is used as-is unless ``refresh`` is True or a
    kind is missing. Credentials/config come from the same env vars the app
    uses (GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_CLOUD_PROJECT,
    FIRESTORE_DATABASE, FIRESTORE_COLLECTION).
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    raw: Dict[str, List[Dict[str, Any]]] = {}
    for kind in _CACHED_KINDS:
        path = _cache_path(cache, kind)
        if not refresh and path.exists():
            logger.info("using cached %s from %s", kind, path)
            raw[kind] = json.loads(path.read_text(encoding="utf-8"))
            continue
        logger.info("fetching %s from Firestore%s", kind, f" for user {user_id}" if user_id else "")
        entities = _fetch_cloud_kind(kind, user_id)
        payload = json.dumps(entities, ensure_ascii=False, indent=1, default=str)
        path.write_text(payload, encoding="utf-8")
        meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "count": len(entities),
                "user_id": user_id}
        _cache_path(cache, f"{kind}.meta").write_text(json.dumps(meta), encoding="utf-8")
        raw[kind] = entities

    documents = [_normalize_document(e, e.get("__id__") or e.get("id") or "") for e in raw["documents"]]
    feedbacks = [_normalize_feedback(e, e.get("__id__") or "") for e in raw["feedbacks"]]
    return {"documents": documents, "feedbacks": feedbacks}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def load_data(
    source: str,
    *,
    backup_dir: str | Path = "data_backup",
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
    user_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    if source == "backup":
        return load_from_backup(backup_dir)
    if source == "cloud":
        return load_from_cloud(cache_dir=cache_dir, refresh=refresh, user_id=user_id)
    raise ValueError(f"unknown source {source!r}; expected 'backup' or 'cloud'")
