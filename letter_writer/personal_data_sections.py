from typing import Dict, Any, List, Optional, Set
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Default background research models - used when user has not configured any
DEFAULT_BACKGROUND_MODELS = ["gemini/gemini-3-flash-preview"]

# Valid vendor prefixes for model IDs (must match ModelVendor enum values)
VALID_VENDOR_KEYS: Set[str] = {"openai", "anthropic", "gemini", "mistral", "grok", "deepseek"}

def get_cv_revisions(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return user_data.get("cv_revisions", [])

def get_models(user_data: Dict[str, Any]) -> List[str]:
    # Check for "models" field, which might be wrapped
    models_data = user_data.get("models")
    return unwrap_for_response("models", models_data) or []

def _validate_model_ids(model_ids: List[str]) -> List[str]:
    """Filter out model IDs with invalid vendor prefixes (e.g. 'google/...' instead of 'gemini/...')."""
    valid = []
    for mid in model_ids:
        vendor = mid.split("/", 1)[0] if "/" in mid else mid
        if vendor in VALID_VENDOR_KEYS:
            valid.append(mid)
        else:
            logger.warning("Dropping invalid background model ID '%s' (unknown vendor '%s')", mid, vendor)
    return valid

def get_background_models(user_data: Dict[str, Any]) -> List[str]:
    """Get the user's background research models, falling back to the default.
    
    Validates vendor prefixes and drops any with unknown vendors (e.g. stale 'google/...' IDs).
    """
    models_data = user_data.get("background_models")
    models = unwrap_for_response("background_models", models_data) or []
    models = _validate_model_ids(models) if models else []
    return models if models else list(DEFAULT_BACKGROUND_MODELS)

def unwrap_for_response(field_name: str, field_data: Any) -> Any:
    if isinstance(field_data, dict) and "value" in field_data:
        return field_data["value"]
    return field_data

def wrap_new_field(field_name: str, value: Any, updated_at: datetime) -> Dict[str, Any]:
    return {
        "value": value,
        "updated_at": updated_at
    }

def get_competence_ratings(user_data: Dict[str, Any]) -> Dict[str, int]:
    # Check "competences" field
    competences_data = user_data.get("competences")
    return unwrap_for_response("competences", competences_data) or {}

def get_style_instructions(user_data: Dict[str, Any]) -> str:
    # Prefer "style" (wrapped { value, updated_at }); fall back to "style_instructions" (legacy/alternate storage)
    for key in ("style", "style_instructions"):
        raw = user_data.get(key)
        if raw is None:
            continue
        out = unwrap_for_response(key, raw)
        if out and isinstance(out, str) and out.strip():
            return out
    return ""

def get_search_instructions(user_data: Dict[str, Any]) -> str:
    # Check "search_instructions" field (wrapped or plain)
    search_data = user_data.get("search_instructions")
    out = unwrap_for_response("search_instructions", search_data)
    return (out or "") if isinstance(out, str) else ""

def merge_on_conflict(updates: Dict[str, Any], existing: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
    # Simple merge logic for optimistic locking retry
    merged = existing.copy()
    merged.update(updates)
    merged["updated_at"] = timestamp
    return merged
