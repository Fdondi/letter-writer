"""Cover letter plan, draft generation, and fancy refinement."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .instructions import (
    _prepend_language_prefix,
    get_structure_instructions,
    get_style_instructions,
)
from .job_extraction import MissingCVError
from .feedback_checks import _extract_json_value
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

KNOWN_WEAKNESSES_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "known_weaknesses",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "weaknesses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "requirement": {"type": "string"},
                            "gap": {"type": "string"},
                        },
                        "required": ["requirement", "gap"],
                    },
                },
            },
            "required": ["weaknesses"],
        },
    },
}

DRAFT_LETTER_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "draft_letter_output",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "draft_letter": {"type": "string"},
                "known_weaknesses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "requirement": {"type": "string"},
                            "gap": {"type": "string"},
                        },
                        "required": ["requirement", "gap"],
                    },
                },
            },
            "required": ["draft_letter", "known_weaknesses"],
        },
    },
}
def normalize_known_weaknesses(data: Any) -> List[Dict[str, str]]:
    """Normalize parsed JSON into known_weaknesses rows with stable ids."""
    raw: List[Any] = []
    if isinstance(data, dict) and isinstance(data.get("known_weaknesses"), list):
        raw = data["known_weaknesses"]
    elif isinstance(data, dict) and isinstance(data.get("weaknesses"), list):
        raw = data["weaknesses"]
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        raw = data["items"]
    elif isinstance(data, list):
        raw = data
    out: List[Dict[str, str]] = []
    seen: set = set()
    for it in raw:
        if not isinstance(it, dict):
            continue
        req = str(it.get("requirement", "")).strip()
        gap = str(it.get("gap", "")).strip()
        desc = str(it.get("description", "")).strip()
        if req and gap:
            key = (req.lower(), gap.lower())
            line_req, line_gap = req, gap
        elif desc:
            key = (desc.lower(), "")
            line_req, line_gap = desc, ""
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": str(uuid.uuid4()), "requirement": line_req, "gap": line_gap})
    return out


def parse_draft_letter_output(data: Any) -> Tuple[str, List[Dict[str, str]]]:
    """Parse draft generation JSON into letter text and normalized known_weaknesses."""
    if isinstance(data, str):
        text = data.strip()
        if not text:
            raise ValueError("empty draft_letter")
        return text, []
    if not isinstance(data, dict):
        raise TypeError("draft output must be a JSON object")
    letter = str(data.get("draft_letter", "")).strip()
    if not letter:
        raise ValueError("missing draft_letter")
    weaknesses = normalize_known_weaknesses(data)
    return letter, weaknesses
def _format_letter_examples(examples: Sequence[TopDocument]) -> str:
    return "\n\n".join(
        f"---- Example #{i+1} [estimated relevance: {ex.get('score', 0)}/10] - {ex.get('company_name', '')} ----\n"
        f"Job Description:\n{ex.get('job_text', '')}\n\n"
        f"Cover Letter:\n{ex.get('letter_text', '')}\n\n"
        for i, ex in enumerate(examples) if (ex.get("letter_text") or "").strip()
    )


def _letter_generation_context(
    *,
    cv_text: str,
    examples_formatted: str,
    company_report: str,
    job_text: str,
    hire_problem: str = "",
) -> str:
    """Shared cached context for letter plan + draft (CV, examples, company, job).

    Passed as ``system_cache_prefix`` so Anthropic caches this block across plan → draft
    (and other calls that share the same documents within the 5-minute TTL).
    """
    hire_block = ""
    hp = (hire_problem or "").strip()
    if hp:
        hire_block = (
            "\n\n========== Hire goal / problem this role should address (from posting extraction) ==========\n"
            + hp
            + "\n==========\n"
        )
    return (
        "========== User CV:\n" + cv_text + "\n==========\n"
        "========== Examples:\n" + examples_formatted + "\n==========\n"
        "========== Company Report:\n" + company_report + "\n==========\n"
        "========== Target Job Description:\n" + job_text + "\n=========="
        + hire_block
    )
def generate_letter_plan(
    cv_text: str,
    examples: Sequence[TopDocument],
    company_report: str,
    job_text: str,
    client: BaseClient,
    trace_dir: Path,
    structure_instructions: str = "",
    additional_user_info: str = "",
    hire_problem: str = "",
    language_prefix: str = "",
    model_role: ModelRole | str | None = None,
) -> str:
    """High-level cover letter plan: strengths, weaknesses to frame, and layout (no draft prose)."""
    company_report = company_report if company_report is not None else ""
    job_text = job_text if job_text is not None else ""
    if cv_text is None or not cv_text or not str(cv_text).strip():
        error_msg = "CV text is missing or empty - cannot generate letter plan"
        logger.error(error_msg, extra={"cv_text": cv_text, "cv_text_type": type(cv_text).__name__})
        raise MissingCVError(error_msg)

    si = (structure_instructions or "").strip() or get_structure_instructions()

    examples_formatted = _format_letter_examples(examples)

    additional_context = ""
    if additional_user_info and additional_user_info.strip():
        additional_context = (
            "\n\n--- ADDITIONAL INFORMATION ABOUT THE APPLICANT ---\n"
            f"{additional_user_info}\n"
            "--- END ADDITIONAL INFORMATION ---\n"
        )

    system = _prepend_language_prefix(
        (
        "You are an expert career strategist. Given the applicant's CV, reference cover letters, "
        "company research, and the target job, produce a **strategic plan** for a cover letter.\n"
        "Do NOT write the cover letter. Output only the plan (~10 lines max, telegraphic).\n"
        "Use the language of the target job description where it matters for clarity.\n\n"
        "**Focus on authentic differentiation:** Identify this applicant's unique strengths and the specific "
        "aspects of the role/company that create compelling fit. Avoid generic strategies or template approaches.\n\n"
        "--- Structure / planning instructions (from the user or defaults) ---\n"
        + si
        + additional_context
        + "\n"
        ),
        language_prefix,
    )

    context = _letter_generation_context(
        cv_text=cv_text,
        examples_formatted=examples_formatted,
        company_report=company_report,
        job_text=job_text,
        hire_problem=hire_problem,
    )
    (trace_dir / "plan_prompt.txt").write_text(context, encoding="utf-8")
    return client.call(
        model_role if model_role is not None else ModelRole.LETTER_PLAN,
        system,
        ["Produce the strategic plan for the cover letter."],
        system_cache_prefix=context,
    )


@traceable(run_type="chain", name="generate_letter")
def generate_letter(
    cv_text: str,
    examples: Sequence[TopDocument],
    company_report: str,
    job_text: str,
    client: BaseClient,
    trace_dir: Path,
    style_instructions: str = "",
    additional_user_info: str = "",
    letter_plan: str = "",
    hire_problem: str = "",
    language_prefix: str = "",
    model_role: ModelRole | str | None = None,
    max_retries: int = 2,
) -> Tuple[str, List[Dict[str, str]]]:
    """Generate a cover letter and objective known_weaknesses in one call (shared context).

    Returns:
        (draft_letter, known_weaknesses)

    Args:
        additional_user_info: User-provided information about themselves relevant to this position (not in CV).
    """
    company_report = company_report if company_report is not None else ""
    job_text = job_text if job_text is not None else ""
    # Validate CV text is present
    if cv_text is None or not cv_text or not str(cv_text).strip():
        error_msg = "CV text is missing or empty - cannot generate cover letter"
        logger.error(error_msg, extra={"cv_text": cv_text, "cv_text_type": type(cv_text).__name__})
        raise MissingCVError(error_msg)
    
    if not style_instructions:
        style_instructions = get_style_instructions()

    examples_formatted = _format_letter_examples(examples)
    
    # Build system prompt with optional additional user info
    additional_context = ""
    if additional_user_info and additional_user_info.strip():
        additional_context = (
            "\n\n--- ADDITIONAL INFORMATION ABOUT THE APPLICANT ---\n"
            "The user has provided the following additional information about themselves that is relevant to this position "
            "but may not be fully captured in their CV. Please consider this when writing the letter:\n"
            f"{additional_user_info}\n"
            "--- END ADDITIONAL INFORMATION ---\n"
        )
    
    plan_block = ""
    lp = (letter_plan or "").strip()
    if lp:
        plan_block = (
            "\n\n--- APPROVED STRATEGIC PLAN (follow this argument structure; do not contradict it) ---\n"
            + lp
            + "\n--- END STRATEGIC PLAN ---\n"
        )

    system = _prepend_language_prefix(
        (
        "You are an expert cover letter writer. Using the user's CV, relevant examples of job descriptions "
        "and their corresponding cover letters, the company report, and the target job description, "
        "produce a personalized, distinctive cover letter. Keep it concise (max 1 page).\n"
        "Remember to use the language of THE TARGET JOB DESCRIPTION, even if some or all of the examples might be in a different language.\n\n"
        "**Use the examples as inspiration for voice, structure, and priorities — NOT as templates to copy.** "
        "Focus on crafting an authentic, specific narrative about THIS applicant's fit for THIS role. "
        "Avoid generic phrases, clichés, and overused patterns (e.g., 'I am writing to express my interest', "
        "'excited by the opportunity', 'strong team player'). Instead, lead with concrete achievements, "
        "specific motivations, or a unique insight about the company or role.\n"
        + style_instructions
        + plan_block
        + additional_context
        + "\n\n"
        "Reply with JSON only: {\"draft_letter\": string, \"known_weaknesses\": [{\"requirement\": string, \"gap\": string}, ...]}.\n"
        "draft_letter is the full cover letter prose.\n"
        "known_weaknesses lists objective requirement gaps the applicant CANNOT fix by editing the letter "
        "(missing mandatory certifications, language level below the posting, absent years-of-experience, degree "
        "requirements not met, etc.). Only include gaps substantiated from the CV, additional info, or job text. "
        "Do not invent gaps. Do not list stylistic preferences or fixable omissions. "
        "The applicant is aware of these gaps and chose to apply anyway. "
        "requirement = what the job asks for; gap = what the applicant actually has or lacks. "
        "Use an empty array when there are no such objective unfixable gaps.\n"
        "When framing a known weakness in draft_letter, be truthful: state the actual level or fact and argue "
        "transferability or willingness to learn. Never mislabel (e.g. do not call B2 'fluent', do not write "
        "'fluent German (B2)').\n"
        ),
        language_prefix,
    )
    context = _letter_generation_context(
        cv_text=cv_text,
        examples_formatted=examples_formatted,
        company_report=company_report,
        job_text=job_text,
        hire_problem=hire_problem,
    )
    (trace_dir / "prompt.txt").write_text(context, encoding="utf-8")

    last_raw = ""
    for attempt in range(1, max_retries + 1):
        try:
            last_raw = client.call(
                model_role if model_role is not None else ModelRole.LETTER_DRAFT,
                system,
                ["Write the personalized cover letter as JSON."],
                response_format=DRAFT_LETTER_JSON_SCHEMA,
                system_cache_prefix=context,
            )
            data = _extract_json_value(last_raw)
            return parse_draft_letter_output(data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(
                "Draft letter JSON parse failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                e,
            )
        except Exception as e:
            logger.warning(
                "Draft letter LLM call failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                e,
            )
    raise RuntimeError(f"Draft letter generation failed after {max_retries} attempts: {last_raw[:500]}")
def fancy_letter(letter: str, client: BaseClient) -> str:
    """Fancy up the letter with a fancy style."""
    system = (
        "You are an expert in writing cover letters. You will receive a cover letter. "
        "Keep as close to the original as possible, but spell the name of the company with the first letter of each paragraph. "
        "The first paragraph should start with the company name itself. For example:\n"
        "Apple -> 'Apple means excellence... Passion for me is... Pluses of employing me... Leading comes natural to me... Excited to contribute...' "
    )
    context = "========== Cover Letter:\n" + letter + "\n==========\n"
    return client.call(
        ModelRole.LETTER_REFINE,
        system,
        ["Please rewrite the cover letter in a more fancy style."],
        system_cache_prefix=context,
    )
