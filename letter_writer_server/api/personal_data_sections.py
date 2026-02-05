"""
Personal data document: NEW fields with per-section update_time for optimistic locking.
We use new field names so we don't mix with old data.

New fields (only these are written):
- competences: { "ratings": { skill: cv_fit 1-5 }, "update_time": ts }
- style: { "instructions": str, "update_time": ts }
- models: { "active": list, "update_time": ts }

Old fields (read-only fallback): competence_ratings, style_instructions, default_models
cv_revisions stays as flat list (each entry has created_at).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# New field config: field_name -> (content_key, default_value)
NEW_FIELD_CONFIG = {
    "competences": ("ratings", {}),
    "style": ("instructions", ""),
    "models": ("active", []),
    "phase_models": ("overrides", {}),  # { phase: { vendor: model_id } }
}


def _to_utc_datetime(dt_or_ts) -> Optional[datetime]:
    """Normalize to timezone-aware UTC datetime for comparison."""
    if dt_or_ts is None:
        return None
    if hasattr(dt_or_ts, "timestamp"):
        ts = dt_or_ts
        if hasattr(ts, "to_datetime"):
            dt = ts.to_datetime()
        else:
            dt = datetime.fromtimestamp(ts.timestamp(), tz=timezone.utc)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(dt_or_ts, datetime):
        dt = dt_or_ts
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _section_update_time(section: Any) -> Optional[datetime]:
    """Extract update_time from a section. None = oldest."""
    if not isinstance(section, dict):
        return None
    return _to_utc_datetime(section.get("update_time"))


def _is_newer(a: Optional[datetime], b: Optional[datetime]) -> bool:
    """True if a is strictly newer than b. None counts as oldest."""
    if a is None:
        return False
    if b is None:
        return True
    return a > b


def wrap_new_field(field: str, value: Any, now: datetime) -> dict:
    """Wrap a value for a new field: { content_key: value, update_time: now }."""
    content_key, _ = NEW_FIELD_CONFIG[field]
    return {content_key: value, "update_time": now}


# ---------------------------------------------------------------------------
# Read helpers: new field first, fall back to old
# ---------------------------------------------------------------------------


def get_competence_ratings(doc: dict) -> dict:
    """Get competence ratings: new field 'competences' first, else old 'competence_ratings'."""
    new = doc.get("competences")
    if isinstance(new, dict) and "ratings" in new:
        r = new["ratings"]
        return r if isinstance(r, dict) else {}
    old = doc.get("competence_ratings")
    return old if isinstance(old, dict) else {}


def get_style_instructions(doc: dict) -> str:
    """Get style instructions: new field 'style' first, else old 'style_instructions'."""
    new = doc.get("style")
    if isinstance(new, dict) and "instructions" in new:
        return new["instructions"] or ""
    old = doc.get("style_instructions")
    return old if isinstance(old, str) else ""


def get_models(doc: dict) -> list:
    """Get default models: new field 'models' first, else old 'default_models'."""
    new = doc.get("models")
    if isinstance(new, dict) and "active" in new:
        a = new["active"]
        return a if isinstance(a, list) else []
    old = doc.get("default_models")
    return old if isinstance(old, list) else []


def get_phase_model_overrides(doc: dict) -> dict:
    """Get phase model overrides: { phase: { vendor: model_id } }."""
    new = doc.get("phase_models")
    if isinstance(new, dict) and "overrides" in new:
        o = new["overrides"]
        return o if isinstance(o, dict) else {}
    return {}


def get_cv_revisions(doc: dict) -> list:
    """Get cv_revisions (stays flat list)."""
    revs = doc.get("cv_revisions")
    return revs if isinstance(revs, list) else []


# ---------------------------------------------------------------------------
# Merge on conflict (optimistic locking retry)
# ---------------------------------------------------------------------------


def _cv_revisions_time(revs: Any) -> Optional[datetime]:
    """Max created_at from cv_revisions list. None if empty or invalid."""
    if not isinstance(revs, list):
        return None
    best = None
    for r in revs:
        if not isinstance(r, dict):
            continue
        t = _to_utc_datetime(r.get("created_at"))
        if t and (best is None or t > best):
            best = t
    return best


def merge_on_conflict(our_updates: dict, current_doc: dict, now: datetime) -> dict:
    """
    Merge our intended updates with the current document after a failed precondition.
    For sections with update_time: keep newer. For cv_revisions: use max(created_at).
    """
    merged = dict(current_doc)
    for key, our_section in our_updates.items():
        if key == "updated_at":
            continue
        if key == "cv_revisions":
            our_ts = _cv_revisions_time(our_section)
            their_ts = _cv_revisions_time(merged.get(key))
        else:
            our_ts = _section_update_time(our_section)
            their_section = merged.get(key)
            their_ts = _section_update_time(their_section) if isinstance(their_section, dict) else None
        if _is_newer(our_ts, their_ts):
            merged[key] = our_section
    merged["updated_at"] = now
    return merged


def unwrap_for_response(field: str, section: dict) -> Any:
    """Extract content from a section for API response."""
    content_key, default = NEW_FIELD_CONFIG.get(field, ("value", None))
    if isinstance(section, dict) and content_key in section:
        return section[content_key]
    return default
