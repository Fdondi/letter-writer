"""Structure, style, and search instructions; translation and company research."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from langsmith import traceable

from . import prompts
from .clients.base import BaseClient, ModelRole

logger = logging.getLogger(__name__)

def get_structure_instructions() -> str:
    """Default instructions for the pre-draft *plan* phase (argument structure, not prose style)."""
    return prompts.load("defaults/structure_instructions.txt")


def get_style_instructions() -> str:
    """Default style instructions."""
    return prompts.load("defaults/style_instructions.txt")


def get_search_instructions() -> str:
    """Default search instructions."""
    return prompts.load("defaults/search_instructions.txt")


def resolve_search_instructions(
    session_instructions: str = "",
    user_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Resolve search instructions: session override, then user profile, then repo default file."""
    if session_instructions and str(session_instructions).strip():
        return str(session_instructions).strip()
    if user_data:
        from .personal_data_sections import get_search_instructions as get_user_search_instructions

        user_instructions = get_user_search_instructions(user_data)
        if user_instructions and user_instructions.strip():
            return user_instructions.strip()
    return get_search_instructions()


@traceable(run_type="chain", name="translate_with_llm")
def translate_with_llm(
    text: str,
    target_language: str,
    user_data: Dict[str, Any],
    user_id: str,
    source_language: Optional[str] = None,
    *,
    level_override: Optional[str] = None,
    instructions_override: Optional[str] = None,
) -> str:
    """Translate text using an LLM, honoring per-language level and instructions."""
    from .client import get_client
    from .clients.base import ModelVendor
    from .cost_tracker import track_api_cost
    from .language_settings import build_translation_system_message

    if not text or not str(text).strip():
        return ""

    client = get_client(ModelVendor.GEMINI)
    system = build_translation_system_message(
        user_data,
        target_language,
        source_language,
        level_override=level_override,
        instructions_override=instructions_override,
    )
    prompt = text
    translated = client.call(ModelRole.TRANSLATION, system, [prompt])
    cost = getattr(client, "total_cost", 0.0) or 0.0
    if cost > 0:
        track_api_cost(
            user_id=user_id,
            phase="translate",
            vendor=ModelVendor.GEMINI.value,
            cost=cost,
            metadata={
                "provider": "llm",
                "character_count": len(text),
                "target_language": target_language,
            },
        )
    return (translated or "").strip()


def _prepend_language_prefix(system: str, language_prefix: str) -> str:
    prefix = (language_prefix or "").strip()
    if not prefix:
        return system
    return prefix + ("\n\n" if system else "") + system


@traceable(run_type="chain", name="company_research")
def company_research(
    company_name: Optional[str],
    job_text: str,
    client: BaseClient,
    trace_dir: Path,
    additional_company_info: str = "",
    search: bool = True,
    model: str | ModelRole = ModelRole.COMPANY_RESEARCH,
    search_instructions: str = "",
    point_of_contact: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Research company information using OpenAI.

    Args:
        company_name: Name of the company to research (may be none if we know the intermediary but not the real one)
        job_text: Job description text
        client: AI client for research
        trace_dir: Directory for tracing
        additional_company_info: User-provided additional context about the company or role
        search: Whether to enable web search tools (default: True)
        model: Model to use (default: ModelRole.COMPANY_RESEARCH)
        search_instructions: User-provided instructions for how to conduct the background search
        point_of_contact: Optional dict with name, role, contact_details, notes (for context only)
    """
    # Use user-provided search instructions or fall back to defaults
    if search_instructions and search_instructions.strip():
        system = search_instructions.strip()
    else:
        system = prompts.load("research/default_system.txt")

    job_text_safe = (job_text or "") if job_text is not None else ""
    company_prompt = ""
    if company_name:
        company_prompt = prompts.render(
            "research/company_prompt.txt",
            company_name=company_name,
            job_excerpt=job_text_safe[:500],
        )

    user_company_context = ""
    if additional_company_info and additional_company_info.strip():
        user_company_context = prompts.render(
            "research/additional_company_info.txt", info=additional_company_info
        )

    # Optional point-of-contact context (e.g. recruiter/intermediary) for disambiguation or tone
    poc_context = ""
    if point_of_contact and isinstance(point_of_contact, dict):
        parts = [f"{k}: {v}" for k, v in point_of_contact.items() if v]
        if parts:
            poc_context = prompts.render("research/point_of_contact.txt", details="; ".join(parts))

    prompt = company_prompt + user_company_context + poc_context
    if len(prompt) == 0:
        logger.warning("Not enough information to research the company.")
        return None

    result = client.call(model, system, [prompt], search=search)
    (trace_dir / "company_research.txt").write_text(result, encoding="utf-8")
    return result
