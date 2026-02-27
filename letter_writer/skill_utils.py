"""Skill name normalization (no external deps). Used by extraction to output core skill names only."""

# Leading modifiers that describe level/proficiency, not the skill itself (case-insensitive).
SKILL_LEADING_MODIFIERS = (
    "fluent ",
    "proficient in ",
    "proficient ",
    "basic ",
    "advanced ",
    "native ",
    "good ",
    "strong ",
    "excellent ",
    "working knowledge of ",
    "knowledge of ",
    "experience with ",
    "experience in ",
)

# Trailing phrases that describe level or domain, not the skill identity.
SKILL_TRAILING_MODIFIERS = (
    " language proficiency",
    " proficiency",
    " language",
    " skills",
)


def core_skill_name(s: str) -> str:
    """Reduce competence to the core skill name without level/proficiency modifiers.

    E.g. 'Fluent German' -> 'German', 'German language proficiency' -> 'German'.
    Modifiers affect importance/level (grading), not what the skill is.
    """
    if not s or not s.strip():
        return ""
    t = " ".join(s.strip().split())
    while True:
        lower = t.lower()
        changed = False
        for mod in sorted(SKILL_LEADING_MODIFIERS, key=len, reverse=True):
            if lower.startswith(mod):
                t = t[len(mod) :].strip()
                changed = True
                break
        if changed:
            continue
        for mod in sorted(SKILL_TRAILING_MODIFIERS, key=len, reverse=True):
            if lower.endswith(mod):
                t = t[: -len(mod)].strip()
                changed = True
                break
        if not changed:
            break
    return " ".join(t.split())
