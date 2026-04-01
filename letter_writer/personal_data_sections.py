from typing import Dict, Any, List, Optional, Set
from datetime import datetime
import logging
from letter_writer.cost_tracker import get_all_model_pricing

logger = logging.getLogger(__name__)

# Default background research models - used when user has not configured any
DEFAULT_BACKGROUND_MODELS = ["gemini/gemini-3-flash-preview"]

# Valid vendor prefixes for model IDs (must match ModelVendor enum values)
VALID_VENDOR_KEYS: Set[str] = {"openai", "anthropic", "gemini", "mistral", "grok", "deepseek"}

def get_cv_revisions(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return user_data.get("cv_revisions", [])


def get_extra_info(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """User-saved notes (from feedback flow and/or CV tab). Each entry should have a stable string id."""
    raw = user_data.get("extra_info")
    if raw is None:
        return []
    unwrapped = unwrap_for_response("extra_info", raw)
    if not isinstance(unwrapped, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in unwrapped:
        if isinstance(it, dict) and it.get("id"):
            out.append(dict(it))
    return out


def _extra_info_entry_has_body(it: Dict[str, Any]) -> bool:
    if str(it.get("manual_text") or "").strip():
        return True
    if str(it.get("user_context") or "").strip():
        return True
    if str(it.get("user_instructions") or "").strip():
        return True
    if str(it.get("observation") or "").strip():
        return True
    lines = it.get("context_lines")
    if isinstance(lines, list) and any(str(x).strip() for x in lines):
        return True
    return False


def format_extra_info_for_cv_appendix(extra_info: List[Dict[str, Any]]) -> str:
    """Markdown block appended to base CV so models treat user notes as part of the CV."""
    nonempty = [it for it in extra_info if isinstance(it, dict) and _extra_info_entry_has_body(it)]
    if not nonempty:
        return ""
    parts: List[str] = [
        "\n\n---\n\n## Additional context (saved notes)\n\n",
        "The following notes were saved from your feedback or your CV settings. Treat them as part of your background, alongside the CV above.\n\n",
    ]
    for i, it in enumerate(nonempty, 1):
        src = str(it.get("source") or "").strip().lower()
        cat = str(it.get("category") or "").strip()
        obs = str(it.get("observation") or "").strip()
        uc = str(it.get("user_context") or "")
        ui = str(it.get("user_instructions") or "").strip()
        lines = it.get("context_lines")
        if isinstance(lines, list):
            ctx_lines = [str(x).strip() for x in lines if str(x).strip()]
        else:
            ctx_lines = []
        manual = str(it.get("manual_text") or "").strip()

        title = f"### Note {i}"
        if cat:
            title += f" ({cat})"
        parts.append(title + "\n\n")
        if src:
            parts.append(f"*Source:* {src}" + ("  \n" if obs or uc or ui or ctx_lines or manual else "\n"))
        if obs:
            parts.append(f"*Related feedback:* {obs}\n\n")
        if ui:
            parts.append(f"*Instructions:* {ui}\n\n")
        if ctx_lines:
            parts.append("*Context lines:*\n")
            for ln in ctx_lines:
                parts.append(f"- {ln}\n")
            parts.append("\n")
        if uc:
            parts.append(f"*Your context:*\n\n{uc}\n\n")
        if manual:
            parts.append(f"{manual}\n\n")
    return "".join(parts).rstrip() + "\n"


def cv_text_with_extra_info(base_cv: str, user_data: Dict[str, Any]) -> str:
    """Base CV text plus formatted extra_info for prompts and checks."""
    appendix = format_extra_info_for_cv_appendix(get_extra_info(user_data))
    if not str(base_cv or "").strip() and appendix:
        return appendix.strip()
    if not appendix:
        return base_cv or ""
    return (base_cv or "").rstrip() + appendix

def get_models(user_data: Dict[str, Any]) -> List[str]:
    # Check for "models" field, which might be wrapped
    models_data = user_data.get("models")
    return unwrap_for_response("models", models_data) or []


def get_agentic_draft_model(user_data: Dict[str, Any]) -> Optional[str]:
    """Get the vendor (or vendor/model_id) used as the sole draft author in per-topic agentic flow.
    Returns None if not set (caller should fall back to first of default_models)."""
    raw = user_data.get("agentic_draft_model")
    out = unwrap_for_response("agentic_draft_model", raw) if raw is not None else None
    return (out or "").strip() or None

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
    if models:
        try:
            searchable_models = get_all_model_pricing(search_only=True)
            searchable_ids = {
                f"{m['vendor_key']}/{m['id']}"
                for vendor_models in searchable_models.values()
                for m in vendor_models
            }
            models = [mid for mid in models if mid in searchable_ids]
        except Exception as e:
            logger.warning("Failed to validate background models against searchable list: %s", e)
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
    unwrapped = unwrap_for_response("competences", competences_data) or {}
    if isinstance(unwrapped, dict) and "ratings" in unwrapped and isinstance(unwrapped.get("ratings"), dict):
        # Backward compatibility for nested shape: {"ratings": {...}}
        return unwrapped.get("ratings") or {}
    return unwrapped if isinstance(unwrapped, dict) else {}

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
