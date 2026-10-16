"""Per-language CEFR levels and instructions for generation and translation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import prompts

_SETTINGS: Dict[str, Any] = prompts.load_json("language/settings.json")
_LINES: Dict[str, Any] = _SETTINGS["lines"]

CEFR_LEVELS: tuple = tuple(_SETTINGS["cefr_levels"])

# Concrete constraints models follow better than "CEFR B2" alone.
CEFR_LEVEL_GUIDANCE: Dict[str, str] = dict(_SETTINGS["level_guidance"])

DEFAULT_LEVEL_BY_CODE: Dict[str, str] = dict(_SETTINGS["default_level_by_code"])
_FALLBACK_LEVEL: str = _SETTINGS["fallback_level"]

DEFAULT_INSTRUCTIONS_BY_CODE: Dict[str, str] = dict(_SETTINGS["default_instructions_by_code"])
DEFAULT_GERMAN_INSTRUCTIONS = DEFAULT_INSTRUCTIONS_BY_CODE["de"]

# Job metadata language names → ISO-ish codes used in default_languages.
# Stored as a list because the substring fallback in resolve_language_code depends on order.
LANGUAGE_CODE_ALIASES: Dict[str, str] = {alias: code for alias, code in _SETTINGS["code_aliases"]}


def _normalize_level(raw: Any) -> str:
    level = str(raw or "").strip()
    if not level:
        return ""
    lower = level.lower()
    if lower == "native":
        return "native"
    upper = level.upper()
    if upper in CEFR_LEVELS:
        return upper
    return ""


def default_level_for_code(code: str) -> str:
    c = str(code or "").strip().lower()
    return DEFAULT_LEVEL_BY_CODE.get(c, _FALLBACK_LEVEL)


def default_instructions_for_code(code: str) -> str:
    c = str(code or "").strip().lower()
    return DEFAULT_INSTRUCTIONS_BY_CODE.get(c, "")


def normalize_language_entry(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code") or "").strip().lower()
    if not code:
        return None
    level = _normalize_level(raw.get("level")) or default_level_for_code(code)
    instructions = str(raw.get("instructions") or "")
    if not instructions.strip() and code in DEFAULT_INSTRUCTIONS_BY_CODE:
        instructions = DEFAULT_INSTRUCTIONS_BY_CODE[code]
    return {
        "code": code,
        "label": str(raw.get("label") or code.upper()),
        "color": raw.get("color"),
        "enabled": raw.get("enabled", True) is not False,
        "level": level,
        "instructions": instructions,
    }


def normalize_default_languages(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        norm = normalize_language_entry(item)
        if norm:
            out.append(norm)
    return out


def get_default_languages(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = user_data.get("default_languages") if user_data else None
    normalized = normalize_default_languages(raw)
    if normalized:
        return normalized
    return normalize_default_languages(_SETTINGS["default_languages"])


def get_language_entry_by_code(user_data: Dict[str, Any], code: str) -> Optional[Dict[str, Any]]:
    target = str(code or "").strip().lower()
    if not target:
        return None
    for entry in get_default_languages(user_data):
        if entry.get("code") == target:
            return entry
    return None


def resolve_language_entry(
    user_data: Dict[str, Any],
    language_hint: str,
    *,
    level_override: Optional[str] = None,
    instructions_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve configured language entry, with optional request-time overrides."""
    code = resolve_language_code(language_hint, user_data)
    if not code:
        return None
    entry = get_language_entry_by_code(user_data, code)
    if not entry:
        entry = normalize_language_entry({"code": code})
    if not entry:
        return None
    entry = dict(entry)
    if level_override:
        normalized = _normalize_level(level_override)
        if normalized:
            entry["level"] = normalized
    if instructions_override is not None:
        entry["instructions"] = str(instructions_override)
    return entry


def resolve_language_code(language_hint: str, user_data: Optional[Dict[str, Any]] = None) -> str:
    """Map a job metadata language string or code to a configured language code."""
    hint = str(language_hint or "").strip().lower()
    if not hint:
        return ""
    if hint in LANGUAGE_CODE_ALIASES:
        return LANGUAGE_CODE_ALIASES[hint]
    if user_data:
        for entry in get_default_languages(user_data):
            code = str(entry.get("code") or "").lower()
            label = str(entry.get("label") or "").lower()
            if hint == code or hint == label:
                return code
    for alias, code in LANGUAGE_CODE_ALIASES.items():
        if alias in hint or hint in alias:
            return code
    return hint[:2] if len(hint) >= 2 else hint


def _language_display_name(entry: Dict[str, Any]) -> str:
    label = str(entry.get("label") or "").strip()
    code = str(entry.get("code") or "").strip()
    return label or code.upper()


def _level_phrase(level: str) -> str:
    if level == "native":
        return _LINES["level_native"]
    return prompts.fill(_LINES["level_cefr"], "language.level_cefr", level=level)


def build_language_instruction_lines(entry: Dict[str, Any], *, for_translation: bool = False) -> List[str]:
    """Build instruction lines for one language entry."""
    name = _language_display_name(entry)
    level = _normalize_level(entry.get("level")) or default_level_for_code(entry.get("code", ""))
    lines: List[str] = []
    key = "translate" if for_translation else "write"
    lines.append(prompts.fill(_LINES[key], f"language.{key}", name=name, level_phrase=_level_phrase(level)))
    guidance = CEFR_LEVEL_GUIDANCE.get(level, "")
    if guidance:
        lines.append(guidance)
    if level in _LINES["capped_levels"]:
        lines.append(_LINES["level_cap"])
    extra = str(entry.get("instructions") or "").strip()
    if extra:
        lines.append(extra)
    return lines


def build_language_system_prefix(
    user_data: Dict[str, Any],
    language_hint: str,
    *,
    level_override: Optional[str] = None,
    instructions_override: Optional[str] = None,
) -> str:
    """Short block prepended to letter-generation system prompts."""
    entry = resolve_language_entry(
        user_data,
        language_hint,
        level_override=level_override,
        instructions_override=instructions_override,
    )
    if not entry:
        return ""
    lines = build_language_instruction_lines(entry, for_translation=False)
    if not lines:
        return ""
    return prompts.fill(_LINES["prefix"], "language.prefix", body="\n".join(lines))


def build_translation_system_message(
    user_data: Dict[str, Any],
    target_language: str,
    source_language: Optional[str] = None,
    *,
    level_override: Optional[str] = None,
    instructions_override: Optional[str] = None,
) -> str:
    entry = resolve_language_entry(
        user_data,
        target_language,
        level_override=level_override,
        instructions_override=instructions_override,
    )
    if not entry:
        entry = {"code": target_language, "label": target_language.upper(), "level": _FALLBACK_LEVEL, "instructions": ""}
    lines = build_language_instruction_lines(entry, for_translation=True)
    src = str(source_language or "").strip()
    parts = [
        _LINES["translator_intro"],
        *lines,
        _LINES["preserve_formatting"],
        _LINES["output_only"],
    ]
    if src:
        parts.insert(1, prompts.fill(_LINES["source_language"], "language.source_language", code=src))
    return "\n".join(parts)


def get_translation_provider(user_data: Dict[str, Any]) -> str:
    raw = user_data.get("translation_provider") if user_data else None
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    provider = str(raw or "google").strip().lower()
    if provider in ("llm", "google"):
        return provider
    return "google"
