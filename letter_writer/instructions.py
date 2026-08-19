"""Structure, style, and search instructions; translation and company research."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from langsmith import traceable

from .clients.base import BaseClient, ModelRole

logger = logging.getLogger(__name__)

def get_structure_instructions() -> str:
    """Load default instructions for the pre-draft *plan* phase (argument structure, not prose style)."""
    path = Path(__file__).parent / "structure_instructions.txt"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (
            "Produce a ~10-line telegraphic strategic plan (elevator pitch). Headings: Strengths (2–3 lines), "
            "Weaknesses (1–2 lines), Structure (3–4 lines: hook, body beats, close). One fact per strength; "
            "honest gap framing only. No sub-bullets, no letter prose."
        )


def get_style_instructions() -> str:
    """Load style instructions from file."""
    style_file = Path(__file__).parent / "style_instructions.txt"
    try:
        return style_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Fallback to default if file doesn't exist
        return (
            "Never mention explicitly that something matches the job description, they should think that by themselves. "
            "Avoid making just a list of 'at X I did Y'. You're telling a story, the stints at specific companies are just supporting evidence for the message. "
            "Mentions of companies should mostly emerge naturally, not be the main structure (At X this, at Y that, etc).\n"
            "Follow the structure: 1. You are great 2. I am great 3. We'll be even greater together 4. Call to action. "
            "Of course, keep that structure implicit, and don't use paragraph titles.\n"
            "Whenever possible, use characters supported by LaTeX. In particular, to the extent that it's reasonable, avoid symbols like & or em-dashes. Do not double-space. "
            "If in doubt, use the version of the character that would be typed by a keyboard. For example ' and not ', or 11th and not 11ᵗʰ.\n"
        )


def get_search_instructions() -> str:
    """Load default search instructions from file."""
    search_file = Path(__file__).parent / "search_instructions.txt"
    try:
        return search_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Fallback to default if file doesn't exist
        return (
            "You are an expert in searching the internet for information about companies.\n\n"
            "IMPORTANT: You are looking at the company from the point of view of a job applicant, not of an investor "
            "or policymaker. Focus on work culture, likely work tasks, and career prospects. Product success, financial "
            "situation, or regulatory difficulties are rarely relevant — only if they threaten to make employment "
            "less secure or more challenging in some way.\n\n"
            "Focus on what distinguishes the company, in the good and bad. Keep it concise but informative.\n"
            "Do NOT include any links, only plain text.\n"
            "Do NOT just repeat the ads the company puts out. Do report what they say about themselves, "
            "but make it clear it's reporting on how they like to present themselves, not the objective truth. "
            "Be inquisitive, almost cynical, read between the lines. If we are writing to a company that likes "
            "to present themselves as trailblazing but is actually quite boring, or vice versa likes to underpromise "
            "but is actually exceptional, we need to consider both aspects.\n"
        )


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
        system = "You are an expert in searching the internet for information about companies."

    job_text_safe = (job_text or "") if job_text is not None else ""
    company_prompt = ""
    if company_name:
        company_prompt = (
            f"Search the internet and write a short, opinionated company report about {company_name}\n"
            f"To disambiguiate, here is how they present themselves: {job_text_safe[:500]}...\n"
            "Do NOT include any links, only plain text.\n"
        )

    # Add user-provided company context if available
    user_company_context = ""
    if additional_company_info and additional_company_info.strip():
        user_company_context = (
            f"\n\nADDITIONAL CONTEXT FROM THE USER:\n"
            f"The applicant has provided the following additional information about the company or role. "
            f"Please verify this information and incorporate relevant findings into your report:\n"
            f"{additional_company_info}\n"
        )

    # Optional point-of-contact context (e.g. recruiter/intermediary) for disambiguation or tone
    poc_context = ""
    if point_of_contact and isinstance(point_of_contact, dict):
        parts = [f"{k}: {v}" for k, v in point_of_contact.items() if v]
        if parts:
            poc_context = "\n\nPOINT OF CONTACT (for context only): " + "; ".join(parts) + "\n"

    prompt = company_prompt + user_company_context + poc_context
    if len(prompt) == 0:
        logger.warning("Not enough information to research the company.")
        return None

    result = client.call(model, system, [prompt], search=search)
    (trace_dir / "company_research.txt").write_text(result, encoding="utf-8")
    return result
