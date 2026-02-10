from typing import Dict, Any, List, Optional
from datetime import datetime

def get_cv_revisions(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return user_data.get("cv_revisions", [])

def get_models(user_data: Dict[str, Any]) -> List[str]:
    # Check for "models" field, which might be wrapped
    models_data = user_data.get("models")
    return unwrap_for_response("models", models_data) or []

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
    # Check "style" field
    style_data = user_data.get("style")
    return unwrap_for_response("style", style_data) or ""

def merge_on_conflict(updates: Dict[str, Any], existing: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
    # Simple merge logic for optimistic locking retry
    merged = existing.copy()
    merged.update(updates)
    merged["updated_at"] = timestamp
    return merged
