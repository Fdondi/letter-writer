"""Parse model id overrides with optional @thinking suffix (UI model picker)."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def split_model_id_and_thinking(model_role: str) -> Tuple[str, str | None]:
    """Return (model_id, thinking_suffix) from e.g. ``gpt-5.5@high``."""
    raw = (model_role or "").strip()
    if "@" not in raw:
        return raw, None
    model_id, raw_suffix = raw.rsplit("@", 1)
    thinking_suffix: str | None = raw_suffix.strip() if raw_suffix else None
    return model_id, thinking_suffix


def thinking_config_for_vendor(vendor_key: str, suffix: str | None) -> Dict[str, Any]:
    """Map UI thinking suffix to vendor-specific thinking config keys."""
    if not suffix:
        return {}
    s = suffix.strip()
    if not s:
        return {}

    vendor = (vendor_key or "").lower()
    if vendor == "openai":
        return {"reasoning_effort": s.lower()}

    if vendor == "gemini":
        if s.lower() in ("none", "off", "null"):
            return {"thinking_level": None}
        if s in ("Low", "Medium", "High"):
            return {"thinking_level": s}
        titled = s.title()
        if titled in ("Low", "Medium", "High"):
            return {"thinking_level": titled}
        return {"thinking_level": s}

    if vendor == "anthropic":
        if s.lower() in ("off", "none", "false"):
            return {"thinking": False}
        return {"thinking": True, "thinking_effort": s.lower()}

    return {}


def apply_model_override_thinking(
    vendor_key: str,
    model_role: str,
) -> Tuple[str, Dict[str, Any]]:
    """Split override model id and build thinking_cfg for client.call."""
    model_id, suffix = split_model_id_and_thinking(model_role)
    return model_id, thinking_config_for_vendor(vendor_key, suffix)


def vendor_key_from_model_selector(value: str) -> str:
    """Extract vendor from vendor-only or vendor/model[@effort] selector value."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if "/" in raw:
        return raw.split("/", 1)[0].strip().lower()
    return raw.lower()
