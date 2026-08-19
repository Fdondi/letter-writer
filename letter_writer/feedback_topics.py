"""Central registry for agentic feedback topics (keys, labels, context builders)."""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from .typed_shapes import TopDocument

# Order matters: downstream topics can review and challenge prior topics' top comments.
FEEDBACK_TOPICS: list[dict[str, str]] = [
    {"key": "instruction", "label": "Instruction"},
    {"key": "company_fit", "label": "Company fit"},
    {"key": "goal_fit", "label": "Goal fit"},
    {"key": "precision", "label": "Precision"},
    {"key": "user_fit", "label": "User fit"},
    {"key": "human", "label": "Human"},
    {"key": "accuracy", "label": "CV accuracy"},
]

AGENTIC_TOPIC_KEYS: tuple[str, ...] = tuple(t["key"] for t in FEEDBACK_TOPICS)

_TOPIC_CONFIG_BY_KEY: dict[str, dict[str, str]] = {t["key"]: t for t in FEEDBACK_TOPICS}


def get_topic_config(key: str) -> dict[str, str]:
    """Return registry entry for *key*; raises KeyError if unknown."""
    try:
        return _TOPIC_CONFIG_BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown feedback topic: {key}") from exc


def get_agentic_topic_context_from_registry(
    topic: str,
    *,
    draft_letter: str,
    cv_text: str,
    company_report: str,
    job_text: str,
    top_docs: Sequence[TopDocument],
    style_instructions: str = "",
    additional_user_info: str = "",
    draft_letters: Optional[dict] = None,
    hire_problem: str = "",
) -> str:
    """Build the topic-specific context string for agentic feedback prompts.

    Returns the context blocks (excluding the draft letter itself) to include in the prompt.
    If draft_letters is provided (vendor -> text), multiple proposals are shown so agents can
    compare and prefer one vendor's choice.
    """
    get_topic_config(topic)

    # Lazy imports avoid a circular dependency with letter_generation / feedback_checks.
    from .feedback_checks import (
        _format_correction,
        _letter_block_for_context,
        _letter_block_multi_proposals,
    )
    from .instructions import get_style_instructions

    if not style_instructions:
        style_instructions = get_style_instructions()
    if draft_letters and len(draft_letters) > 0:
        letter_block = _letter_block_multi_proposals(draft_letters)
    else:
        letter_block = _letter_block_for_context(draft_letter)

    if topic == "instruction":
        return (
            "========== Style Instructions:\n" + style_instructions + "\n==========\n\n" + letter_block
        )
    if topic == "accuracy":
        today_str = date.today().isoformat()
        extra = (
            "\n(Use this when judging dates: today's date is "
            + today_str
            + ". Treat dates after this as future-dated.)\n\n"
        )
        if additional_user_info and additional_user_info.strip():
            extra += (
                "========== User's additional info (relevant but not in CV):\n"
                + additional_user_info + "\n==========\n\n"
            )
        return "========== User CV:\n" + cv_text + "\n==========\n\n" + extra + letter_block
    if topic == "precision":
        return (
            "========== Company Report:\n" + company_report + "\n==========\n"
            + "========== Job Offer:\n" + job_text + "\n==========\n\n" + letter_block
        )
    if topic == "company_fit":
        return (
            "========== Company Report:\n" + company_report + "\n==========\n"
            + "========== Job Offer:\n" + job_text + "\n==========\n\n" + letter_block
        )
    if topic == "goal_fit":
        hp = (hire_problem or "").strip()
        prefix = ""
        if hp:
            prefix = (
                "========== Hire goal / problem this role solves (structured extraction from the posting):\n"
                + hp
                + "\n==========\n"
            )
        return (
            prefix
            + "========== Company Report:\n" + company_report + "\n==========\n"
            + "========== Job Offer:\n" + job_text + "\n==========\n\n" + letter_block
        )
    if topic == "user_fit":
        examples_formatted = "\n\n".join(
            f"---- Example #{i+1} - {ex.get('company_name', '?')} ----\n"
            f"Cover Letter:\n{ex.get('letter_text', '')}\n\n"
            for i, ex in enumerate(top_docs) if ex.get("letter_text")
        )
        if not examples_formatted.strip():
            examples_formatted = "(No reference letters available.)"
        cv_block = (cv_text or "").strip()
        if not cv_block:
            cv_block = "(No CV text was provided in this session.)"
        extra = ""
        if additional_user_info and additional_user_info.strip():
            extra = (
                "\n\n========== User's additional info (relevant but not fully captured in CV):\n"
                + additional_user_info.strip()
                + "\n==========\n"
            )
        return (
            "========== Reference Examples:\n"
            + examples_formatted
            + "\n==========\n\n"
            + "========== User CV:\n"
            + cv_block
            + "\n==========\n"
            + extra
            + "\n"
            + letter_block
        )
    if topic == "human":
        rewritten = [
            ex for ex in top_docs
            if ex.get("letter_text") and isinstance(ex.get("ai_letters"), list) and ex["ai_letters"]
        ]
        if not rewritten:
            return letter_block + "(No revision examples available.)"
        examples_formatted = "\n\n".join(
            f"---- Example #{i+1} - {ex.get('company_name', '?')} ----\n"
            "Initial cover letters:\n"
            + "\n\n".join(
                f"[attempt {j+1}]:\n"
                + (f"(Rating: {al.get('rating')}/5)\n" if al.get("rating") else "")
                + (f"(Feedback: \"{al.get('comment')}\")\n" if al.get("comment") else "")
                + (al.get("text", "") or "")
                + (
                    "\n\nUser corrections:\n"
                    + "\n".join(
                        _format_correction(corr)
                        for corr in (al.get("user_corrections") or [])
                        if isinstance(corr, dict)
                        and (
                            (corr.get("type") == "full" and corr.get("original") is not None and corr.get("edited") is not None)
                            or (corr.get("type") == "diff" and (corr.get("original") is not None or corr.get("edited") is not None))
                        )
                    )
                    if al.get("user_corrections") else ""
                )
                for j, al in enumerate(ex["ai_letters"])
                if isinstance(al, dict) and al.get("text")
            )
            + "\n\nRevised cover letter:\n" + (ex.get("letter_text") or "")
            for i, ex in enumerate(rewritten)
        )
        return "========== Reference Examples (initial + user corrections + revised):\n" + examples_formatted + "\n==========\n\n" + letter_block
    return letter_block
