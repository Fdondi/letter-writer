"""Pure autocomplete helpers (no Firestore / LLM imports)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from letter_writer.clients.base import ModelVendor
from letter_writer.personal_data_sections import (
    VALID_VENDOR_KEYS,
    get_autocomplete_models,
    get_models,
)

_SHORTCUT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Completion cache: fetch a long buffer from the LLM, serve display-sized chunks locally.
AUTOCOMPLETE_CACHE_WORD_MULTIPLIER = 10
AUTOCOMPLETE_CACHE_EXTEND_THRESHOLD = 0.8


def derive_ctrl_letter_map_from_models(models: List[str]) -> Dict[str, str]:
    """Assign Ctrl+letter shortcuts from vendor initial, advancing if taken."""
    used: set[str] = set()
    out: Dict[str, str] = {}
    for composite in models or []:
        raw = str(composite or "").strip()
        if not raw:
            continue
        vendor = raw.split("/", 1)[0].strip().lower()
        if not vendor:
            continue
        idx = _SHORTCUT_LETTERS.find(vendor[0].upper())
        if idx < 0:
            idx = 0
        letter = _SHORTCUT_LETTERS[idx]
        while letter in used and idx < len(_SHORTCUT_LETTERS) - 1:
            idx += 1
            letter = _SHORTCUT_LETTERS[idx]
        if letter in used:
            continue
        used.add(letter)
        out[letter] = raw
    return out


def merge_ctrl_letter_map(
    cycle_models: List[str],
    stored_map: Optional[Dict[str, str]],
    role_defaults: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Apply stored Ctrl+letter assignments; fill unassigned cycle models with vendor-initial defaults."""
    defaults_dict = role_defaults if isinstance(role_defaults, dict) else {}
    cycle: List[str] = []
    for raw in cycle_models or []:
        normalized = normalize_autocomplete_model_key(str(raw or "").strip(), defaults_dict)
        if normalized and normalized not in cycle:
            cycle.append(normalized)

    normalized_stored: Dict[str, str] = {}
    if isinstance(stored_map, dict):
        for map_letter, model in stored_map.items():
            key = str(map_letter or "").strip().upper()[:1]
            raw_model = str(model or "").strip()
            if not key or not raw_model:
                continue
            normalized = normalize_autocomplete_model_key(raw_model, defaults_dict)
            if normalized:
                normalized_stored[key] = normalized

    derived = derive_ctrl_letter_map_from_models(cycle)
    model_to_stored_letter: Dict[str, str] = {}
    for stored_letter, composite in normalized_stored.items():
        if composite in cycle and composite not in model_to_stored_letter:
            model_to_stored_letter[composite] = stored_letter

    used_letters: set[str] = set()
    out: Dict[str, str] = {}

    for composite in cycle:
        letter = model_to_stored_letter.get(composite)
        if letter and letter not in used_letters:
            out[letter] = composite
            used_letters.add(letter)

    for composite in cycle:
        if composite in out.values():
            continue
        default_letter = next((ltr for ltr, model in derived.items() if model == composite), None)
        if default_letter and default_letter not in used_letters:
            out[default_letter] = composite
            used_letters.add(default_letter)
            continue
        for letter in _SHORTCUT_LETTERS:
            if letter not in used_letters:
                out[letter] = composite
                used_letters.add(letter)
                break

    return out


def _clients_dir() -> Path:
    return Path(__file__).resolve().parent / "clients"


def _role_model_from_entry(entry: Any) -> Optional[str]:
    if isinstance(entry, dict):
        model = entry.get("model")
        return str(model).strip() if model else None
    if isinstance(entry, str):
        return entry.strip() or None
    return None


def _role_defaults_for_config_role(role_name: str, *, fallbacks: tuple[str, ...]) -> Dict[str, str]:
    """Return vendor_key -> composite model id for each vendor with ``role_name`` in client JSON."""
    out: Dict[str, str] = {}
    clients_dir = _clients_dir()
    if not clients_dir.exists():
        return out
    for json_path in sorted(clients_dir.glob("*.json")):
        vendor_key = json_path.stem
        if vendor_key not in VALID_VENDOR_KEYS:
            continue
        try:
            cfg = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        roles = cfg.get("roles", {}) if isinstance(cfg, dict) else {}
        if not isinstance(roles, dict):
            continue
        model_id = _role_model_from_entry(roles.get(role_name))
        if not model_id:
            for fb in fallbacks:
                model_id = _role_model_from_entry(roles.get(fb))
                if model_id:
                    break
        if model_id:
            out[vendor_key] = f"{vendor_key}/{model_id}"
    return out


def get_autocomplete_role_defaults() -> Dict[str, str]:
    """Return vendor_key -> composite model id for each vendor with an autocomplete role."""
    return _role_defaults_for_config_role("autocomplete", fallbacks=("letter_draft",))


def get_autocomplete_plan_role_defaults() -> Dict[str, str]:
    """Return vendor_key -> composite model id for each vendor with an autocomplete_plan role."""
    return _role_defaults_for_config_role("autocomplete_plan", fallbacks=("letter_plan", "letter_draft"))


def normalize_autocomplete_model_key(
    model_key: str,
    role_defaults: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Normalize vendor-only keys to vendor/model composite ids."""
    raw = (model_key or "").strip()
    if not raw:
        return None
    defaults = role_defaults if role_defaults is not None else get_autocomplete_role_defaults()
    if "/" in raw:
        vendor_part = raw.split("/", 1)[0].strip().lower()
        if vendor_part not in VALID_VENDOR_KEYS:
            return None
        return raw
    vendor = raw.lower()
    if vendor not in VALID_VENDOR_KEYS:
        return None
    return defaults.get(vendor, vendor)


def normalize_autocomplete_model_list(
    models: List[str],
    role_defaults: Optional[Dict[str, str]] = None,
) -> List[str]:
    defaults = role_defaults if role_defaults is not None else get_autocomplete_role_defaults()
    out: List[str] = []
    seen: set[str] = set()
    for m in models:
        normalized = normalize_autocomplete_model_key(str(m or ""), defaults)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def default_autocomplete_models(role_defaults: Optional[Dict[str, str]] = None) -> List[str]:
    defaults = role_defaults if role_defaults is not None else get_autocomplete_role_defaults()
    return list(defaults.values())


def default_autocomplete_plan_model(role_defaults: Optional[Dict[str, str]] = None) -> str:
    defaults = role_defaults if role_defaults is not None else get_autocomplete_plan_role_defaults()
    if defaults.get("openai"):
        return defaults["openai"]
    if defaults:
        return next(iter(defaults.values()))
    return "openai"


def resolve_autocomplete_plan_model(
    user_data: Dict[str, Any],
    *,
    explicit_model: Optional[str] = None,
) -> str:
    from letter_writer.personal_data_sections import get_autocomplete_plan_model

    role_defaults = get_autocomplete_plan_role_defaults()
    if explicit_model and str(explicit_model).strip():
        normalized = normalize_autocomplete_model_key(str(explicit_model).strip(), role_defaults)
        if normalized:
            return normalized
    stored = get_autocomplete_plan_model(user_data)
    if stored:
        return stored
    return default_autocomplete_plan_model(role_defaults)


def parse_autocomplete_vendor(model_key: str) -> ModelVendor:
    raw = (model_key or "").strip()
    if not raw:
        raise ValueError("model key is required")
    vendor_part = raw.split("/", 1)[0].strip().lower()
    if vendor_part not in VALID_VENDOR_KEYS:
        raise ValueError(f"Unknown vendor '{vendor_part}'. Valid: {sorted(VALID_VENDOR_KEYS)}")
    return ModelVendor(vendor_part)


def strip_autocomplete_continuation_overlap(
    suggestion: str,
    text_before_cursor: str,
) -> Tuple[str, bool]:
    """Drop a leading suggestion prefix that repeats the suffix already written at the cursor."""
    sug = (suggestion or "").strip()
    written = text_before_cursor or ""
    if not sug or not written:
        return sug, False
    max_n = min(len(written), len(sug))
    for n in range(max_n, 0, -1):
        if written[-n:] == sug[:n]:
            return sug[n:].lstrip(), True
    return sug, False


def truncate_autocomplete_suggestion(
    text: str,
    *,
    max_words: int,
    stop_on_period: bool,
) -> Tuple[str, Optional[str]]:
    """Return trimmed suggestion and optional truncation reason."""
    if not text:
        return "", None
    out = text.strip()
    if not out:
        return "", None

    truncated_by: Optional[str] = None

    if stop_on_period:
        m = re.search(r"\.(?:\s|$)", out)
        if m:
            end = m.end()
            if end < len(out):
                truncated_by = "period"
            out = out[:end].rstrip()

    words = out.split()
    if max_words > 0 and len(words) > max_words:
        out = " ".join(words[:max_words])
        if truncated_by is None:
            truncated_by = "max_words"
        elif truncated_by != "max_words":
            truncated_by = f"{truncated_by},max_words"

    if out and not out.endswith((".", "!", "?")) and stop_on_period and truncated_by == "period":
        if not out.endswith("."):
            out = out + "."

    return out, truncated_by


def autocomplete_cache_fetch_max_words(display_max_words: int) -> int:
    """Word cap for a single LLM fetch (display limit × multiplier)."""
    display = max(1, min(100, int(display_max_words)))
    return min(1000, display * AUTOCOMPLETE_CACHE_WORD_MULTIPLIER)


def should_extend_autocomplete_cache(consumed_offset: int, raw_length: int) -> bool:
    """True when at least 80% of the cached buffer has been handed out."""
    if raw_length <= 0 or consumed_offset <= 0:
        return False
    return consumed_offset >= int(raw_length * AUTOCOMPLETE_CACHE_EXTEND_THRESHOLD)


def slice_next_autocomplete_chunk(
    raw: str,
    offset: int,
    *,
    max_words: int,
    stop_on_period: bool,
) -> Tuple[str, int, Optional[str], bool]:
    """
    Take the next display chunk from a cached raw completion.

    Returns (chunk, new_offset, truncated_by, has_more).
    """
    raw_text = raw or ""
    if offset >= len(raw_text):
        return "", offset, None, False
    rest = raw_text[offset:]
    leading = len(rest) - len(rest.lstrip())
    work = rest.lstrip()
    if not work:
        return "", offset, None, False
    chunk, truncated_by = truncate_autocomplete_suggestion(
        work,
        max_words=max_words,
        stop_on_period=stop_on_period,
    )
    if not chunk:
        return "", offset, None, False
    if work.startswith(chunk):
        consumed_in_work = len(chunk)
    else:
        # Truncation may normalize whitespace; advance by word count as fallback.
        consumed_in_work = len(" ".join(chunk.split()))
    new_offset = offset + leading + consumed_in_work
    tail = raw_text[new_offset:].strip()
    has_more = bool(tail)
    return chunk, new_offset, truncated_by, has_more


def finalize_autocomplete_suggestion(
    raw_suggestion: str,
    *,
    max_words: int,
    stop_on_period: bool,
    text_before_cursor: str,
) -> Tuple[str, Optional[str], List[str]]:
    """Truncate, strip overlap with text already at the cursor, and collect warnings."""
    suggestion, truncated_by = truncate_autocomplete_suggestion(
        (raw_suggestion or "").strip(),
        max_words=max_words,
        stop_on_period=stop_on_period,
    )
    warnings: List[str] = []
    stripped, had_overlap = strip_autocomplete_continuation_overlap(
        suggestion, text_before_cursor
    )
    if had_overlap:
        if stripped:
            suggestion = stripped
        elif suggestion.strip():
            warnings.append("continuation_only_repeated_existing_text")
            suggestion = ""
            truncated_by = None
    return suggestion, truncated_by, warnings


def resolve_autocomplete_model(
    user_data: Dict[str, Any],
    *,
    explicit_model: Optional[str] = None,
    ctrl_letter: Optional[str] = None,
    shift_letter: Optional[str] = None,
) -> str:
    role_defaults = get_autocomplete_role_defaults()

    if explicit_model and str(explicit_model).strip():
        normalized = normalize_autocomplete_model_key(str(explicit_model).strip(), role_defaults)
        if normalized:
            return normalized

    letter = ctrl_letter or shift_letter
    if letter:
        from letter_writer.personal_data_sections import get_autocomplete_ctrl_letter_map

        letter_map = get_autocomplete_ctrl_letter_map(user_data)
        key = str(letter).strip().upper()[:1]
        if key and key in letter_map:
            normalized = normalize_autocomplete_model_key(letter_map[key], role_defaults)
            if normalized:
                return normalized

    models = get_autocomplete_models(user_data)
    if models:
        return models[0]

    defaults = default_autocomplete_models(role_defaults)
    if defaults:
        return defaults[0]

    legacy = get_models(user_data)
    if legacy:
        normalized = normalize_autocomplete_model_key(legacy[0], role_defaults)
        if normalized:
            return normalized

    return role_defaults.get("openai", "openai")


def next_model_in_cycle(current: str, user_data: Dict[str, Any]) -> str:
    role_defaults = get_autocomplete_role_defaults()
    models = get_autocomplete_models(user_data)
    if not models:
        models = default_autocomplete_models(role_defaults)
    if not models:
        legacy = get_models(user_data)
        models = normalize_autocomplete_model_list(list(legacy) if legacy else [], role_defaults)
    if not models:
        return normalize_autocomplete_model_key(current, role_defaults) or role_defaults.get("openai", "openai")
    current_norm = normalize_autocomplete_model_key(current, role_defaults) or current
    try:
        idx = models.index(current_norm)
        return models[(idx + 1) % len(models)]
    except ValueError:
        return models[0]


def _strip_json_fence(text: str) -> str:
    raw = (text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_autocomplete_plan_batch_json(
    raw: str, *, expected_count: int
) -> Tuple[Dict[str, str], Dict[str, str], str]:
    """Parse batch plan LLM JSON: plans, proposals, and context_summary in one response."""
    text = _strip_json_fence(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Plan batch response is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("Plan batch response must be a JSON object")
    plans_raw = obj.get("plans")
    if not isinstance(plans_raw, dict):
        raise ValueError("Plan batch response missing 'plans' object")
    plans_out: Dict[str, str] = {}
    for key, val in plans_raw.items():
        plan_text = str(val or "").strip()
        if plan_text:
            plans_out[str(key)] = plan_text
    if expected_count > 0:
        missing = [str(i) for i in range(expected_count) if str(i) not in plans_out]
        if missing:
            raise ValueError(f"Plan batch missing sections: {', '.join(missing)}")

    proposals_out: Dict[str, str] = {}
    proposals_raw = obj.get("proposals")
    if isinstance(proposals_raw, dict):
        for key, val in proposals_raw.items():
            proposal_text = str(val or "").strip()
            if proposal_text:
                proposals_out[str(key)] = proposal_text
    if expected_count > 0:
        missing_proposals = [
            str(i) for i in range(expected_count) if str(i) not in proposals_out
        ]
        if missing_proposals:
            raise ValueError(
                f"Plan batch missing hidden proposals for sections: {', '.join(missing_proposals)}"
            )

    context_summary = str(obj.get("context_summary") or "").strip()
    if not context_summary:
        raise ValueError("Plan batch response missing 'context_summary' string")
    return plans_out, proposals_out, context_summary


def parse_autocomplete_section_plan_response(raw: str) -> Tuple[str, str]:
    """
    Parse single-section plan response: markdown bullets + full hidden draft for the section.

    Accepts optional ``## Proposal`` / ``## Hidden proposal`` section after the plan.
    """
    text = (raw or "").strip()
    if not text:
        return "", ""
    proposal_markers = (
        "\n## Proposal",
        "\n## Hidden proposal",
        "\n## Hidden Proposal",
        "\n### Proposal",
    )
    plan_text = text
    proposal_text = ""
    for marker in proposal_markers:
        idx = text.find(marker)
        if idx >= 0:
            plan_text = text[:idx].strip()
            proposal_text = text[idx + len(marker) :].strip()
            if proposal_text.startswith(":"):
                proposal_text = proposal_text[1:].strip()
            break
    if not proposal_text:
        raise ValueError(
            "Section plan response must include a '## Proposal' section with full section draft text"
        )
    if not plan_text:
        raise ValueError("Section plan response missing tactical bullet plan")
    return plan_text, proposal_text


def build_all_sections_plan_user_prompt(
    *,
    sections: List[Dict[str, Any]],
    context_summary_max_chars: int = 0,
) -> str:
    """Prompt for one LLM call: plans, proposals, and compressed context in one JSON object."""
    if not sections:
        return ""
    lines: List[str] = [
        "Plan every cover letter section below so they work together as one coherent letter.",
        "Assign distinct, non-overlapping tactical points to each section — no bullet should belong in two sections.",
        "Each section gets 3–5 markdown bullets only (tactical outline) "
        "and a full hidden draft of that section's letter text (complete paragraphs, not an overview).",
        "",
        "Sections:",
    ]
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip() or f"Section {i + 1}"
        goal = str(sec.get("description") or "").strip()
        lines.append(f"{i}. **{title}**")
        lines.append(
            f"   Goal: {goal or '(infer from title and letter structure)'}"
        )
        lines.append("")
    summary_budget = max(1, int(context_summary_max_chars)) if context_summary_max_chars else 0
    lines.extend(
        [
            'Respond with JSON only (no markdown code fences):',
            '{"plans": {"0": "- bullet\\n- bullet", "1": "..."}, '
            '"proposals": {"0": "Full draft paragraph(s) for section 0", "1": "..."}, '
            '"context_summary": "dense applicant/job facts for these plans"}',
            "Keys for plans and proposals are 0-based section indices as strings.",
            "plans: markdown bullets per section (tactical outline only, not letter prose).",
            "proposals: the full, finished cover-letter text for that section only — real paragraphs the "
            "applicant could send as-is (same language/tone as the job; no bullets, no meta commentary, "
            "no overview or summary of what to write). Sections must read as one coherent letter when concatenated.",
            "context_summary: plain-text compression of the applicant and job context from the system message — "
            "only facts needed to execute these plans (omit irrelevant CV lines, examples, and metadata). "
            + (
                f"Target length about {summary_budget} characters (moderate overrun is acceptable)."
                if summary_budget
                else "Keep it as short as possible while preserving plan-critical facts."
            ),
        ]
    )
    return "\n".join(lines)


def build_section_plan_user_prompt(
    *,
    sections: List[Dict[str, Any]],
    section_index: int,
) -> str:
    """Prompt body for replanning one section; siblings may include goal + existing plan."""
    if not sections:
        return ""
    section_index = max(0, min(section_index, len(sections) - 1))
    target = sections[section_index] if isinstance(sections[section_index], dict) else {}
    title = str(target.get("title") or "").strip() or f"Section {section_index + 1}"
    goal = str(target.get("description") or "").strip()
    body = str(target.get("body") or "").strip()

    lines: List[str] = [
        f"Plan the cover letter section: **{title}**",
        "",
        "Section goal (what this paragraph must accomplish):",
        goal or "(no goal provided — infer from section title and letter structure)",
    ]
    if body:
        lines.extend(["", "Draft text already written for this section:", body])

    others: List[str] = []
    for i, sec in enumerate(sections):
        if i == section_index or not isinstance(sec, dict):
            continue
        st = str(sec.get("title") or f"Section {i + 1}").strip()
        sg = str(sec.get("description") or "").strip()
        sp = str(sec.get("plan") or "").strip()
        sb = str(sec.get("body") or "").strip()
        block = f"### {st}\nGoal: {sg or '(no goal)'}"
        if sp:
            block += f"\nPlan:\n{sp}"
        elif sb:
            block += f"\nWritten: {sb[:400]}{'…' if len(sb) > 400 else ''}"
        others.append(block)
    if others:
        lines.extend(
            [
                "",
                "Other sections (already scoped — do not repeat their points in your plan):",
                *others,
            ]
        )

    lines.extend(
        [
            "",
            "Output in two parts:",
            "1) Tactical plan: markdown bullet points only (3–5 bullets, no more).",
            "Stay tightly focused on the section goal — each bullet is what to address, not draft prose.",
            "2) Hidden proposal: after a line `## Proposal`, write the complete cover-letter text for this "
            "section only — full paragraph(s) ready for the final letter (same language as the job; "
            "not an outline, overview, or notes about what to say).",
            "Use the job/CV context: align strengths, acknowledge mismatches honestly, bridge skill gaps when relevant.",
        ]
    )
    return "\n".join(lines)


def context_summary_max_chars(full_context_len: int) -> int:
    """Target length for plan-derived context summary (at most 1/10 of source context)."""
    if full_context_len <= 0:
        return 0
    return max(1, full_context_len // 10)


# Only hard-truncate when the model is wildly over budget (see finalize_plan_context_summary).
CONTEXT_SUMMARY_TRUNCATE_MULTIPLIER = 3


def finalize_plan_context_summary(
    summary: str,
    *,
    full_context_len: int,
) -> Tuple[str, List[str]]:
    """Apply the 1/10 target. Moderate overruns are kept; truncate only above 3× the target."""
    warnings: List[str] = []
    text = (summary or "").strip()
    max_chars = context_summary_max_chars(full_context_len)
    if max_chars <= 0:
        if text:
            warnings.append("context_summary_unexpected:full_context_empty")
        return "", warnings
    if not text:
        warnings.append("context_summary_empty")
        return "", warnings
    truncate_at = max_chars * CONTEXT_SUMMARY_TRUNCATE_MULTIPLIER
    if len(text) > truncate_at:
        warnings.append(
            f"context_summary_exceeded_max_length:{len(text)}>{max_chars}"
            f"(truncated_to:{max_chars})"
        )
        text = text[:max_chars].rstrip()
    return text, warnings


def build_context_summary_user_prompt(
    *,
    sections: List[Dict[str, Any]],
    plans: Dict[str, str],
) -> str:
    """Prompt for compressing applicant/job context after section plans exist."""
    lines: List[str] = [
        "The applicant and job context are in the system message above.",
        "Section plans for this cover letter:",
        "",
    ]
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip() or f"Section {i + 1}"
        goal = str(sec.get("description") or "").strip()
        plan = str(plans.get(str(i)) or sec.get("plan") or "").strip()
        lines.append(f"### {title}")
        if goal:
            lines.append(f"Goal: {goal}")
        if plan:
            lines.append(f"Plan:\n{plan}")
        lines.append("")
    lines.extend(
        [
            "Write a dense summary of ONLY the applicant/job facts needed to execute these plans.",
            "Omit anything not referenced by the plans (irrelevant jobs, skills, company trivia).",
            "Use the same language as the job description for role-specific terms.",
            "Plain prose or short bullets — no preamble, no JSON.",
            "Stay within the maximum character count given in the system message.",
        ]
    )
    return "\n".join(lines).strip()


def build_autocomplete_cache_prefix(
    *,
    cv_text: str,
    job_text: str,
    style_instructions: str,
    additional_user_info: str,
    additional_company_info: str,
    structure_instructions: str = "",
    company_report: str = "",
    top_docs: Optional[List[Dict[str, Any]]] = None,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
    plan_context_summary: str = "",
    active_section_plan: str = "",
    active_section_proposal: str = "",
    section_proposal_stale: bool = False,
) -> str:
    parts: List[str] = []
    summary = (plan_context_summary or "").strip()
    if summary:
        parts.append(
            "========== Context (plan-relevant summary) ==========\n" + summary
        )
    elif cv_text.strip():
        parts.append("========== User CV ==========\n" + cv_text.strip())

    if not summary:
        examples = format_autocomplete_top_docs(top_docs or [])
        if examples.strip():
            parts.append("========== Examples ==========\n" + examples.strip())

        if company_report.strip():
            parts.append("========== Company Report ==========\n" + company_report.strip())

        job_meta = format_autocomplete_job_metadata(
            company_name=company_name,
            job_title=job_title,
            location=location,
            language=language,
            salary=salary,
            requirements=requirements or [],
            competences=competences or {},
            point_of_contact=point_of_contact,
        )
        if job_meta.strip():
            parts.append("========== Job metadata ==========\n" + job_meta.strip())

        if job_text.strip():
            parts.append("========== Target Job Description ==========\n" + job_text.strip())
        if additional_user_info.strip():
            parts.append(
                "========== Additional user info ==========\n" + additional_user_info.strip()
            )
        if additional_company_info.strip():
            parts.append(
                "========== Additional company info ==========\n"
                + additional_company_info.strip()
            )
    if structure_instructions.strip():
        parts.append("========== Structure instructions ==========\n" + structure_instructions.strip())
    if style_instructions.strip():
        parts.append("========== Style instructions ==========\n" + style_instructions.strip())
    if active_section_plan.strip():
        parts.append(
            "========== Section writing plan (active paragraph) ==========\n"
            + active_section_plan.strip()
        )
    if active_section_proposal.strip():
        stale_note = ""
        if section_proposal_stale:
            stale_note = (
                "\n[Note: the applicant may have edited this section since this guide was written; "
                "treat it as approximate, not authoritative.]\n"
            )
        parts.append(
            "========== Section draft candidate (hidden proposal — full text for this paragraph) =========="
            + stale_note
            + "\n"
            + active_section_proposal.strip()
        )
    return "\n\n".join(parts)


def format_autocomplete_top_docs(top_docs: List[Dict[str, Any]]) -> str:
    """Format example letters like vendor draft (generate_letter)."""
    if not top_docs:
        return ""
    blocks = []
    idx = 0
    for ex in top_docs:
        letter_text = (ex.get("letter_text") or "").strip()
        if not letter_text:
            continue
        idx += 1
        score = ex.get("score", 0)
        company = ex.get("company_name", "")
        job = ex.get("job_text", "")
        blocks.append(
            f"---- Example #{idx} [estimated relevance: {score}/10] - {company} ----\n"
            f"Job Description:\n{job}\n\n"
            f"Cover Letter:\n{letter_text}\n"
        )
    return "\n\n".join(blocks)


def sections_to_body_text(sections: Optional[List[Dict[str, Any]]]) -> str:
    """Join section bodies only — titles/descriptions are editor guidance, not final copy."""
    if not sections:
        return ""
    parts: List[str] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        body = str(sec.get("body") or "").strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts)


def build_autocomplete_draft_prefix(
    sections: List[Dict[str, Any]],
    active_index: int,
    cursor_in_section: int,
) -> str:
    """
    Markdown draft for the LLM: sections up to and including the active one.
    Earlier sections include full body; the active section includes body[:cursor].
    Later sections are omitted.
    """
    if not sections:
        return ""
    active_index = max(0, min(active_index, len(sections) - 1))
    blocks: List[str] = ["Please continue:"]
    for i, sec in enumerate(sections):
        if i > active_index:
            break
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip()
        description = str(sec.get("description") or "").strip()
        body = str(sec.get("body") or "")
        if i < active_index:
            body_slice = body
        else:
            cur = max(0, min(cursor_in_section, len(body)))
            body_slice = body[:cur]
        block_lines: List[str] = []
        if title:
            block_lines.append(f"# {title}")
        if description:
            block_lines.append(f"## {description}")
        if body_slice:
            block_lines.append(body_slice.rstrip())
        if block_lines:
            blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


def format_autocomplete_job_metadata(
    *,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = []
    if company_name.strip():
        lines.append(f"Company: {company_name.strip()}")
    if job_title.strip():
        lines.append(f"Role: {job_title.strip()}")
    if location.strip():
        lines.append(f"Location: {location.strip()}")
    if language.strip():
        lines.append(f"Language: {language.strip()}")
    if salary.strip():
        lines.append(f"Salary: {salary.strip()}")

    req = [str(r).strip() for r in (requirements or []) if str(r).strip()]
    if req:
        lines.append("Requirements:")
        lines.extend(f"- {r}" for r in req)

    comp = competences or {}
    if comp:
        lines.append("Competences (need / candidate level):")
        for skill, val in comp.items():
            if not str(skill).strip():
                continue
            if isinstance(val, dict):
                need = val.get("need")
                level = val.get("level")
                lines.append(f"- {skill}: need={need}, level={level}")
            else:
                lines.append(f"- {skill}: {val}")

    if point_of_contact and isinstance(point_of_contact, dict):
        poc_lines = []
        for key in ("name", "role", "contact_details", "company", "notes"):
            v = point_of_contact.get(key)
            if v and str(v).strip():
                poc_lines.append(f"{key}: {str(v).strip()}")
        if poc_lines:
            lines.append("Point of contact:")
            lines.extend(poc_lines)

    return "\n".join(lines)
