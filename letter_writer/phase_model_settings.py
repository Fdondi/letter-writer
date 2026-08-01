"""Per-vendor role model overrides; defaults from clients/<vendor>.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .autocomplete_core import _role_model_from_entry, normalize_autocomplete_model_key
from .clients.base import ModelRole, VALID_VENDOR_KEYS, normalize_config_vendor_key

# Roles users may override in Settings (grouped by flow in vendor_model_flows.py).
CONFIGURABLE_VENDOR_ROLES = (
    "extraction",
    "rag_ranker",
    "company_research",
    "letter_plan",
    "letter_draft",
    "letter_refine",
    "feedback",
    "feedback_review",
    "feedback_context",
    "autocomplete",
    "autocomplete_plan",
    "agentic",
)

# Legacy alias
PHASE_ROLES = ("letter_plan", "letter_draft", "letter_refine")

_ROLE_FALLBACKS: Dict[str, tuple[str, ...]] = {
    "extraction": (),
    "rag_ranker": (),
    "company_research": (),
    "letter_plan": ("letter_draft",),
    "letter_draft": (),
    "letter_refine": ("letter_draft",),
    "feedback": (),
    "feedback_review": ("feedback",),
    "feedback_context": ("feedback",),
    "autocomplete": ("letter_draft",),
    "autocomplete_plan": ("letter_plan", "letter_draft"),
    "agentic": ("letter_draft",),
}


def _clients_dir() -> Path:
    return Path(__file__).resolve().parent / "clients"


def _thinking_suffix_from_role_entry(vendor_key: str, entry: Any) -> Optional[str]:
    """Map a vendor JSON role entry to a UI @suffix (mirrors model_override thinking keys)."""
    if not isinstance(entry, dict):
        return None
    vendor = vendor_key.lower()
    if vendor == "openai":
        effort = entry.get("reasoning_effort")
        if effort is not None and str(effort).strip().lower() not in ("", "none"):
            return str(effort).strip().lower()
        return None
    if vendor == "gemini":
        level = entry.get("thinking_level")
        if level is None:
            return None
        s = str(level).strip()
        if s.lower() in ("none", "null", "off", ""):
            return "none"
        return s
    if vendor == "anthropic":
        thinking = entry.get("thinking")
        if thinking is False or str(thinking).lower() in ("false", "off", "none"):
            return "off"
        effort = entry.get("effort") or entry.get("thinking_effort")
        if effort:
            return str(effort).strip().lower()
        if thinking is True:
            return "medium"
        return None
    return None


def _composite_from_role_entry(vendor_key: str, entry: Any) -> Optional[str]:
    model_id = _role_model_from_entry(entry)
    if not model_id:
        return None
    base = f"{vendor_key}/{model_id}"
    suffix = _thinking_suffix_from_role_entry(vendor_key, entry)
    if suffix and suffix.lower() not in ("none", "off"):
        return f"{base}@{suffix}"
    return base


def get_role_defaults_for_config_role(
    role_name: str,
    *,
    fallbacks: tuple[str, ...] = (),
) -> Dict[str, str]:
    """vendor_key -> composite model id from clients/<vendor>.json roles[role_name]."""
    out: Dict[str, str] = {}
    clients_dir = _clients_dir()
    if not clients_dir.exists():
        return out
    fb = fallbacks if fallbacks else _ROLE_FALLBACKS.get(role_name, ())
    for json_path in sorted(clients_dir.glob("*.json")):
        vendor_key = normalize_config_vendor_key(json_path.stem)
        if vendor_key not in VALID_VENDOR_KEYS:
            continue
        try:
            cfg = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        roles = cfg.get("roles", {}) if isinstance(cfg, dict) else {}
        if not isinstance(roles, dict):
            continue
        entry = roles.get(role_name)
        composite = _composite_from_role_entry(vendor_key, entry)
        if not composite:
            for fb_role in fb:
                composite = _composite_from_role_entry(vendor_key, roles.get(fb_role))
                if composite:
                    break
        if composite:
            out[vendor_key] = composite
    return out


def get_letter_plan_role_defaults() -> Dict[str, str]:
    return get_role_defaults_for_config_role("letter_plan", fallbacks=_ROLE_FALLBACKS["letter_plan"])


def get_letter_draft_role_defaults() -> Dict[str, str]:
    return get_role_defaults_for_config_role("letter_draft", fallbacks=_ROLE_FALLBACKS["letter_draft"])


def get_letter_refine_role_defaults() -> Dict[str, str]:
    return get_role_defaults_for_config_role("letter_refine", fallbacks=_ROLE_FALLBACKS["letter_refine"])


def get_phase_role_defaults(role: str) -> Dict[str, str]:
    if role not in CONFIGURABLE_VENDOR_ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    return get_role_defaults_for_config_role(role, fallbacks=_ROLE_FALLBACKS.get(role, ()))


def _role_defaults_for_role(role: str) -> Dict[str, str]:
    return get_phase_role_defaults(role)


def normalize_vendor_role_model_overrides(raw: Any) -> Dict[str, Dict[str, str]]:
    """Validate vendor -> role -> composite keys."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for vendor, roles in raw.items():
        vendor_key = str(vendor or "").strip().lower()
        if vendor_key not in VALID_VENDOR_KEYS or not isinstance(roles, dict):
            continue
        cleaned: Dict[str, str] = {}
        for role in CONFIGURABLE_VENDOR_ROLES:
            if role not in roles:
                continue
            val = str(roles.get(role) or "").strip()
            if not val:
                continue
            normalized = normalize_autocomplete_model_key(val, _role_defaults_for_role(role))
            if normalized:
                cleaned[role] = normalized
        if cleaned:
            out[vendor_key] = cleaned
    return out


# Legacy name
normalize_phase_model_overrides = normalize_vendor_role_model_overrides


def get_merged_vendor_role_models(
    overrides: Dict[str, Dict[str, str]],
    *,
    roles: tuple[str, ...] = CONFIGURABLE_VENDOR_ROLES,
) -> Dict[str, Dict[str, str]]:
    """vendor -> role -> effective composite (config default unless overridden)."""
    merged: Dict[str, Dict[str, str]] = {}
    for role in roles:
        defaults = _role_defaults_for_role(role)
        for vendor, composite in defaults.items():
            merged.setdefault(vendor, {})[role] = composite
    for vendor, role_map in (overrides or {}).items():
        if vendor not in merged:
            merged[vendor] = {}
        if not isinstance(role_map, dict):
            continue
        for role in roles:
            val = str(role_map.get(role) or "").strip()
            if val:
                merged[vendor][role] = val
    return merged


# Legacy compose-only merge
def get_merged_phase_models(overrides: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return get_merged_vendor_role_models(overrides, roles=PHASE_ROLES)


def resolve_client_model_role(
    vendor: str,
    role: str,
    overrides: Dict[str, Dict[str, str]],
) -> Union[ModelRole, str]:
    """Return ModelRole or model-id override string for client.call()."""
    vendor_key = str(vendor or "").strip().lower()
    role_key = str(role or "").strip()
    override = (overrides or {}).get(vendor_key, {}).get(role_key)
    if override and "/" in override:
        vendor_part, model_part = override.split("/", 1)
        if vendor_part.strip().lower() == vendor_key and model_part.strip():
            return model_part.strip()
    try:
        return ModelRole(role_key)
    except ValueError:
        return ModelRole.LETTER_DRAFT
