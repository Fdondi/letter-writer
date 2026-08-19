"""Cover letter rewrite incorporating phased feedback."""

import logging
from pathlib import Path
from typing import Any, List

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .feedback_checks import (
    FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN,
    FEEDBACK_CONTEXT_USER_SOURCE,
    _is_no_comment,
)
from .instructions import _prepend_language_prefix, get_style_instructions

logger = logging.getLogger(__name__)

def _rewrite_dimension_text(val: Any) -> str:
    """Build the refinement prompt fragment for one dimension (legacy string or item list)."""
    if isinstance(val, str):
        if _is_no_comment(val):
            return ""
        s = (val or "").strip()
        if s.upper().endswith("PLEASE FIX"):
            return s[: -len("PLEASE FIX")].rstrip()
        return s
    if isinstance(val, list):
        lines: List[str] = []
        for it in val:
            if not isinstance(it, dict):
                continue
            if it.get("type") != "PLEASE_FIX":
                continue
            o = (it.get("observation") or "").strip()
            if not o:
                continue

            status = str(it.get("status") or "").strip().upper()
            if status not in ("NOT_NEEDED", "SUFFICIENT", "INPUT_NEEDED"):
                status = "NOT_NEEDED"
            machine_ctx: List[str] = []
            user_ctx_from_field: List[str] = []
            cf = it.get("context_field")
            if isinstance(cf, dict) and isinstance(cf.get("items"), list):
                for raw in (cf.get("items", []) or []):
                    if isinstance(raw, str):
                        t = raw.strip()
                        if t:
                            machine_ctx.append(t)
                        continue
                    if isinstance(raw, dict):
                        t = str(raw.get("text") or "").strip()
                        src = str(raw.get("source") or "").strip().upper()
                        if not t:
                            continue
                        if src == FEEDBACK_CONTEXT_USER_SOURCE:
                            user_ctx_from_field.append(t)
                        elif src in FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN:
                            machine_ctx.append(f"[{src}] {t}")
                        else:
                            machine_ctx.append(t)
            user_context = (it.get("user_context") or "").strip() if isinstance(it.get("user_context") or "", str) else ""
            input_declined = bool(it.get("input_declined")) if status == "INPUT_NEEDED" else False

            # Keep the base observation first (this is the actionable critique).
            extra: List[str] = []
            if machine_ctx:
                extra.append("Available context: " + "; ".join(machine_ctx))
            user_provided_bits: List[str] = []
            if status == "INPUT_NEEDED" and user_context:
                user_provided_bits.append(user_context)
            user_provided_bits.extend(user_ctx_from_field)
            if user_provided_bits:
                extra.append("User-provided context: " + "; ".join(user_provided_bits))
            if (
                status == "INPUT_NEEDED"
                and input_declined
                and not user_context
                and not user_ctx_from_field
            ):
                extra.append(
                    "User approved this point without supplying missing facts; do not invent facts."
                )
            if extra:
                lines.append(o + "\n  - " + "\n  - ".join(extra))
            else:
                lines.append(o)
        return "\n".join(lines)
    return ""


@traceable(run_type="chain", name="rewrite_letter")
def rewrite_letter(
    original_letter: str,
    instruction_feedback: Any,
    accuracy_feedback: Any,
    precision_feedback: Any,
    company_fit_feedback: Any,
    goal_fit_feedback: Any,
    user_fit_feedback: Any,
    human_feedback: Any,
    client: BaseClient,
    trace_dir: Path,
    letter_plan: str = "",
    style_instructions: str = "",
    language_prefix: str = "",
    model_role: ModelRole | str | None = None,
) -> str:
    """Rewrite the cover letter incorporating all feedback."""
    si = (style_instructions or "").strip() or get_style_instructions()
    plan_block = ""
    lp = (letter_plan or "").strip()
    if lp:
        plan_block = (
            "\n\n--- APPROVED STRATEGIC PLAN (preserve alignment with this plan unless feedback explicitly overrides) ---\n"
            + lp
            + "\n--- END STRATEGIC PLAN ---\n"
        )
    system = _prepend_language_prefix(
        (
        "You are an expert cover letter editor. Given an original cover letter and multiple "
        "pieces of feedback, rewrite the letter to address all concerns while maintaining "
        "its core message and keeping it concise (max 1 page).\n"
        "Writing style and tone expectations:\n"
        + si
        + plan_block
        + "\n"
        ),
        language_prefix,
    )
    had_feedback = False
    context_parts = ["========== Original Cover Letter:\n" + original_letter + "\n==========\n"]
    dim_blocks = (
        ("Instruction Feedback", instruction_feedback),
        ("Accuracy Feedback", accuracy_feedback),
        ("Precision Feedback", precision_feedback),
        ("Company Fit Feedback", company_fit_feedback),
        ("Goal Fit Feedback", goal_fit_feedback),
        ("User Fit Feedback", user_fit_feedback),
        ("Human Feedback", human_feedback),
    )
    for title, val in dim_blocks:
        block = _rewrite_dimension_text(val)
        if not block:
            continue
        had_feedback = True
        context_parts.append(f"========== {title}:\n" + block + "\n==========\n")
    if not had_feedback:
        logger.info("No feedback provided, returning original letter.")
        return original_letter

    context = "".join(context_parts)
    user_prompt = (
        "Please rewrite the cover letter incorporating all the feedback. Output only the revised letter.\n"
        "ONLY address the feedback that was provided. Do not change any part of the letter except what is touched by feedback. \n"
        "Feedback is meant to call attention to specific aspects, but can be short-sighted in context. "
        "If you see that no feedback meaningfully needs to be addressed, output NO REVISIONS and end the answer.\n"
    )
    (trace_dir / "rewrite_prompt.txt").write_text(context + "\n\n" + user_prompt, encoding="utf-8")
    revised_letter = client.call(
        model_role if model_role is not None else ModelRole.LETTER_REFINE,
        system,
        [user_prompt],
        system_cache_prefix=context,
    )
    if "NO REVISIONS" in revised_letter:
        logger.info("No revisions needed, returning original letter.")
        return original_letter
    return revised_letter 
