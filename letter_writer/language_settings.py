"""Per-language CEFR levels and instructions for generation and translation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

CEFR_LEVELS: tuple = ("A1", "A2", "B1", "B2", "C1", "C2", "native")

# Concrete constraints models follow better than "CEFR B2" alone.
CEFR_LEVEL_GUIDANCE: Dict[str, str] = {
    "A1": "Use A1 (beginner) wording only: very short sentences, basic vocabulary, present tense where possible.",
    "A2": "Use A2 (elementary) wording: simple connected sentences, frequent everyday vocabulary, limited subordination.",
    "B1": "Use B1 (intermediate) wording: clear standard language on familiar topics; avoid advanced idioms and complex literary phrasing.",
    "B2": (
        "Use B2 (upper-intermediate) wording only: fluent but clearly non-native. "
        "Prefer common vocabulary and straightforward syntax. "
        "Avoid C1/C2 idioms, rhetorical flourishes, academic register, and near-native nuance."
    ),
    "C1": "Use C1 (advanced) wording: sophisticated but natural; complex sentences allowed.",
    "C2": "Use C2 (proficient) wording: near-native precision and nuance.",
    "native": "Use native-speaker naturalness and idiomatic phrasing.",
}

DEFAULT_LEVEL_BY_CODE: Dict[str, str] = {
    "de": "B2",
    "en": "C2",
}

DEFAULT_GERMAN_INSTRUCTIONS = (
    "Verwende echte Umlaute (ä, ö, ü, ß) — niemals ae, oe, ue oder ss als Ersatz."
)

DEFAULT_INSTRUCTIONS_BY_CODE: Dict[str, str] = {
    "de": DEFAULT_GERMAN_INSTRUCTIONS,
}

# Job metadata language names → ISO-ish codes used in default_languages
LANGUAGE_CODE_ALIASES: Dict[str, str] = {
    "de": "de",
    "deutsch": "de",
    "german": "de",
    "ger": "de",
    "en": "en",
    "english": "en",
    "eng": "en",
    "fr": "fr",
    "french": "fr",
    "français": "fr",
    "francais": "fr",
    "es": "es",
    "spanish": "es",
    "español": "es",
    "espanol": "es",
    "it": "it",
    "italian": "it",
    "italiano": "it",
    "nl": "nl",
    "dutch": "nl",
    "nederlands": "nl",
    "pt": "pt",
    "portuguese": "pt",
    "português": "pt",
    "portugues": "pt",
}


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
    return DEFAULT_LEVEL_BY_CODE.get(c, "B2")


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
    return normalize_default_languages(
        [
            {"code": "de", "label": "DE", "color": "#3b82f6", "enabled": True},
            {"code": "en", "label": "EN", "color": "#6366f1", "enabled": True},
        ]
    )


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
        return "as a native speaker would"
    return f"at CEFR {level} level"


def build_language_instruction_lines(entry: Dict[str, Any], *, for_translation: bool = False) -> List[str]:
    """Build instruction lines for one language entry."""
    name = _language_display_name(entry)
    level = _normalize_level(entry.get("level")) or default_level_for_code(entry.get("code", ""))
    lines: List[str] = []
    if for_translation:
        lines.append(f"MANDATORY: Translate into {name} {_level_phrase(level)}.")
    else:
        lines.append(f"MANDATORY: Write in {name} {_level_phrase(level)}.")
    guidance = CEFR_LEVEL_GUIDANCE.get(level, "")
    if guidance:
        lines.append(guidance)
    if level in ("A1", "A2", "B1", "B2"):
        lines.append(
            "Do not use vocabulary, idioms, or sentence complexity above this level — "
            "even if examples, the CV, or style instructions suggest higher proficiency."
        )
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
    body = "\n".join(lines)
    return (
        "--- Language requirements (override linguistic complexity from examples/style) ---\n"
        f"{body}\n"
        "--- End language requirements ---\n\n"
    )


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
        entry = {"code": target_language, "label": target_language.upper(), "level": "B2", "instructions": ""}
    lines = build_language_instruction_lines(entry, for_translation=True)
    src = str(source_language or "").strip()
    parts = [
        "You are a professional translator.",
        *lines,
        "Preserve formatting, line breaks, and markdown where present.",
        "Output only the translation — no preamble, notes, or quotes around the result.",
    ]
    if src:
        parts.insert(1, f"Source language code: {src}.")
    return "\n".join(parts)


def get_translation_provider(user_data: Dict[str, Any]) -> str:
    raw = user_data.get("translation_provider") if user_data else None
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    provider = str(raw or "google").strip().lower()
    if provider in ("llm", "google"):
        return provider
    return "google"
