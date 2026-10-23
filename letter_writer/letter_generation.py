"""Cover letter plan, draft generation, and fancy refinement."""

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langsmith import traceable

from . import prompts
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

KNOWN_WEAKNESSES_JSON_SCHEMA: Dict[str, Any] = prompts.load_json("schemas/known_weaknesses.json")

DRAFT_LETTER_JSON_SCHEMA: Dict[str, Any] = prompts.load_json("schemas/draft_letter.json")
PARAGRAPH_CONTINUE_JSON_SCHEMA: Dict[str, Any] = prompts.load_json("schemas/paragraph_continue.json")


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
        prompts.render(
            "generation/example.txt",
            number=i + 1,
            score=ex.get("score", 0),
            company_name=ex.get("company_name", ""),
            job_text=ex.get("job_text", ""),
            letter_text=ex.get("letter_text", ""),
        )
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
        hire_block = prompts.render("generation/context_hire_block.txt", hire_problem=hp)
    return prompts.render(
        "generation/context.txt",
        cv=cv_text,
        examples=examples_formatted,
        company_report=company_report,
        job=job_text,
        hire_block=hire_block,
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
        additional_context = prompts.render(
            "generation/plan_additional_info.txt", info=additional_user_info
        )

    system = _prepend_language_prefix(
        prompts.render(
            "generation/plan_system.txt",
            structure_instructions=si,
            additional_context=additional_context,
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
        [prompts.load("generation/plan_user.txt")],
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
        additional_context = prompts.render(
            "generation/draft_additional_info.txt", info=additional_user_info
        )

    plan_block = ""
    lp = (letter_plan or "").strip()
    if lp:
        plan_block = prompts.render("generation/draft_plan_block.txt", plan=lp)

    system = _prepend_language_prefix(
        prompts.render(
            "generation/draft_system.txt",
            style_instructions=style_instructions,
            plan_block=plan_block,
            additional_context=additional_context,
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
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            last_raw = client.call(
                model_role if model_role is not None else ModelRole.LETTER_DRAFT,
                system,
                [prompts.load("generation/draft_user.txt")],
                response_format=DRAFT_LETTER_JSON_SCHEMA,
                system_cache_prefix=context,
            )
            data = _extract_json_value(last_raw)
            return parse_draft_letter_output(data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            last_error = str(e)
            logger.warning(
                "Draft letter JSON parse failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                e,
            )
        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Draft letter LLM call failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                e,
            )
            # Permanent provider failures (billing, auth) will not succeed on retry.
            err_l = last_error.lower()
            if any(
                marker in err_l
                for marker in (
                    "credit balance",
                    "insufficient_quota",
                    "insufficient credits",
                    "invalid_api_key",
                    "authentication",
                    "permission denied",
                    "unauthorized",
                )
            ):
                raise RuntimeError(f"Draft letter generation failed: {last_error}") from e
    detail = (last_raw or last_error or "").strip()
    raise RuntimeError(
        f"Draft letter generation failed after {max_retries} attempts: {detail[:500]}"
    )


def split_letter_paragraphs(text: str) -> List[str]:
    """Split on blank lines (same rule as the web ``splitIntoParagraphs``)."""
    stripped = (text or "").strip()
    if not stripped:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n", stripped) if p.strip()]


def _paragraph_system(
    template: str,
    *,
    style_instructions: str,
    additional_user_info: str,
    language_prefix: str,
) -> str:
    additional_context = ""
    if additional_user_info and additional_user_info.strip():
        additional_context = prompts.render(
            "generation/draft_additional_info.txt", info=additional_user_info
        )
    return _prepend_language_prefix(
        prompts.render(
            template,
            style_instructions=style_instructions or get_style_instructions(),
            additional_context=additional_context,
        ),
        language_prefix,
    )


@traceable(run_type="chain", name="regenerate_paragraph")
def regenerate_paragraph(
    paragraphs: Sequence[str],
    index: int,
    feedback: str,
    cv_text: str,
    examples: Sequence[TopDocument],
    company_report: str,
    job_text: str,
    client: BaseClient,
    style_instructions: str = "",
    additional_user_info: str = "",
    hire_problem: str = "",
    language_prefix: str = "",
    model_role: ModelRole | str | None = None,
) -> str:
    """Rewrite paragraph ``index`` of ``paragraphs`` in place of the rest of the letter."""
    if not 0 <= index < len(paragraphs):
        raise ValueError(f"paragraph index {index} out of range (0..{len(paragraphs) - 1})")
    marked = "\n\n".join(
        f">>>\n{p}\n<<<" if i == index else p for i, p in enumerate(paragraphs)
    )
    system = _paragraph_system(
        "generation/paragraph_regenerate_system.txt",
        style_instructions=style_instructions,
        additional_user_info=additional_user_info,
        language_prefix=language_prefix,
    )
    context = _letter_generation_context(
        cv_text=cv_text,
        examples_formatted=_format_letter_examples(examples),
        company_report=company_report or "",
        job_text=job_text or "",
        hire_problem=hire_problem,
    )
    user = prompts.render(
        "generation/paragraph_regenerate_user.txt",
        letter=marked,
        feedback=(feedback or "").strip() or "(none given: write a stronger alternative)",
    )
    text = client.call(
        model_role if model_role is not None else ModelRole.PARAGRAPH,
        system,
        [user],
        system_cache_prefix=context,
    )
    return _strip_paragraph_markers(text)


def _strip_paragraph_markers(text: str) -> str:
    out = (text or "").strip()
    for marker in (">>>", "<<<"):
        out = out.replace(marker, "")
    return out.strip()


@traceable(run_type="chain", name="continue_letter_paragraph")
def continue_letter_paragraph(
    letter_so_far: str,
    cv_text: str,
    examples: Sequence[TopDocument],
    company_report: str,
    job_text: str,
    client: BaseClient,
    instructions: str = "",
    style_instructions: str = "",
    additional_user_info: str = "",
    hire_problem: str = "",
    language_prefix: str = "",
    model_role: ModelRole | str | None = None,
) -> Tuple[str, bool]:
    """Next paragraph after ``letter_so_far``. Returns (paragraph, letter_complete)."""
    system = _paragraph_system(
        "generation/paragraph_continue_system.txt",
        style_instructions=style_instructions,
        additional_user_info=additional_user_info,
        language_prefix=language_prefix,
    )
    context = _letter_generation_context(
        cv_text=cv_text,
        examples_formatted=_format_letter_examples(examples),
        company_report=company_report or "",
        job_text=job_text or "",
        hire_problem=hire_problem,
    )
    instructions_block = ""
    if (instructions or "").strip():
        instructions_block = prompts.render(
            "generation/paragraph_instructions_block.txt", instructions=instructions.strip()
        )
    user = prompts.render(
        "generation/paragraph_continue_user.txt",
        letter_so_far=(letter_so_far or "").strip() or "(nothing written yet)",
        instructions_block=instructions_block,
    )
    raw = client.call(
        model_role if model_role is not None else ModelRole.PARAGRAPH,
        system,
        [user],
        response_format=PARAGRAPH_CONTINUE_JSON_SCHEMA,
        system_cache_prefix=context,
    )
    return parse_paragraph_continue_output(raw)


def parse_paragraph_continue_output(raw: str) -> Tuple[str, bool]:
    """Tolerant parse: JSON ``{paragraph, letter_complete}`` or bare prose."""
    try:
        data = _extract_json_value(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = None
    if isinstance(data, dict) and str(data.get("paragraph") or "").strip():
        return str(data["paragraph"]).strip(), bool(data.get("letter_complete"))
    text = (raw or "").strip()
    if not text or text.startswith("{"):
        raise ValueError("paragraph continuation returned no paragraph")
    return text, False


def fancy_letter(letter: str, client: BaseClient) -> str:
    """Fancy up the letter with a fancy style."""
    system = prompts.load("generation/fancy_system.txt")
    context = "========== Cover Letter:\n" + letter + "\n==========\n"
    return client.call(
        ModelRole.LETTER_REFINE,
        system,
        [prompts.load("generation/fancy_user.txt")],
        system_cache_prefix=context,
    )
