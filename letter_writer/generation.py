import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from pathlib import Path
from openai import OpenAI
from langsmith import traceable

from .config import TRACE_DIR
from .clients.base import BaseClient, ModelSize

logger = logging.getLogger(__name__)


class MissingCVError(Exception):
    """Catastrophic error: CV text is missing or empty when it should be present."""
    pass

REQUIRED_SUFFIXES = ("NO COMMENT", "PLEASE FIX")


def _has_required_suffix(text: str) -> bool:
    """Check whether text ends with one of the required review markers."""
    normalized = (text or "").strip().upper()
    return any(normalized.endswith(marker) for marker in REQUIRED_SUFFIXES)


@traceable(run_type="chain", name="call_with_required_suffix")
def _call_with_required_suffix(
    client: BaseClient,
    model_size: ModelSize,
    system: str,
    prompt: str,
    *,
    search: bool = False,
    max_retries: int = 2,
) -> str:
    """Call an LLM and enforce that the reply ends with NO COMMENT or PLEASE FIX."""
    suffix_instruction = (
        " ALWAYS end your response with exactly one of these phrases: "
        "'NO COMMENT' (no issues) or 'PLEASE FIX' (issues found). "
        "Do not add anything after that final phrase."
    )
    enforced_system = system + suffix_instruction

    last_response = ""
    for attempt in range(1, max_retries + 1):
        response = client.call(model_size, enforced_system, [prompt], search=search)
        last_response = response.strip()
        if _has_required_suffix(last_response):
            return last_response
        print(
            f"[WARN] Missing required suffix in review response "
            f"(attempt {attempt}/{max_retries}); retrying..."
        )

    # As a final safety net, append PLEASE FIX to avoid false approval.
    print(f"[WARN] Missing required suffix in review response "
            f"(attempt {attempt}/{max_retries}); appending PLEASE FIX")
    return f"{last_response}\nPLEASE FIX"


def _is_no_comment(feedback: str) -> bool:
    """Return True only if feedback explicitly ends with NO COMMENT."""
    return (feedback or "").strip().upper().endswith("NO COMMENT")


def _clean_metadata_val(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return ", ".join(str(x).strip() for x in val if str(x).strip())
    return str(val).strip()


def _write_trace(trace_dir: Path | None, system: str, prompt: str, raw: str) -> None:
    if trace_dir is None:
        return
    trace_dir.mkdir(parents=True, exist_ok=True)
    try:
        (trace_dir / "prompt.txt").write_text(f"SYSTEM:\n{system}\n\nPROMPT:\n{prompt}", encoding="utf-8")
        (trace_dir / "raw.txt").write_text(raw, encoding="utf-8")
    except Exception:
        pass


@traceable(run_type="chain", name="extract_job_metadata_no_requirements")
def extract_job_metadata_no_requirements(
    job_text: str,
    client: BaseClient,
    trace_dir: Path | None = None,
) -> Dict[str, Any]:
    """Extract job metadata except key competences (company, role, location, etc.). No CV needed."""
    system = (
        "You are an assistant that extracts a concise job summary from a job description. "
        "Return strict JSON with these keys only: company_name, job_title, location, language, salary, point_of_contact. "
        "Stick to one language unless it's really mixed. A few english words don't make english a language used. "
        "Use null for unknown values. "
        "For point_of_contact, extract if present: name, role (their role in the company), contact_details (email, phone, etc.), and notes (any note about them or how to contact them). "
        "If no point of contact is found, set point_of_contact to null. "
        "Do not add any additional keys or prose."
    )
    prompt = (
        "Job description:\n"
        f"{job_text}\n\n"
        "Respond with JSON only. Example format:\n"
        '{"company_name":"Acme","job_title":"Senior Engineer","location":"Remote","language":"English","salary":"€80-100k","point_of_contact":{"name":"John Doe","role":"HR Manager","contact_details":"john.doe@acme.com","notes":"Please contact via email"}}'
    )
    raw = client.call(ModelSize.TINY, system, [prompt])
    _write_trace(trace_dir, system, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    poc_data = data.get("point_of_contact")
    point_of_contact = None
    if poc_data and isinstance(poc_data, dict):
        point_of_contact = {
            "name": _clean_metadata_val(poc_data.get("name")),
            "role": _clean_metadata_val(poc_data.get("role")),
            "contact_details": _clean_metadata_val(poc_data.get("contact_details")),
            "notes": _clean_metadata_val(poc_data.get("notes")),
        }
        if not point_of_contact["name"] and not point_of_contact["contact_details"]:
            point_of_contact = None

    return {
        "company_name": _clean_metadata_val(data.get("company_name")),
        "job_title": _clean_metadata_val(data.get("job_title")),
        "location": _clean_metadata_val(data.get("location")),
        "language": _clean_metadata_val(data.get("language")),
        "salary": _clean_metadata_val(data.get("salary")),
        "point_of_contact": point_of_contact,
    }


LEVEL_LABELS = ("Newbie", "Amateur", "Brief experience", "Professional", "Senior professional")

DEFAULT_NEED_SEMANTICS: Dict[str, str] = {
    "critical": "central to the job",
    "expected": "necessary, but not specific to the job",
    "nice to have": "desirable but not required",
    "useful": "useful but not central",
    "necessary": "required for the role",
    "marginally useful": "optional, slight plus",
}


@traceable(run_type="chain", name="extract_key_competences")
def extract_key_competences(
    job_text: str,
    client: BaseClient,
    trace_dir: Path | None = None,
    need_categories: tuple[str, ...] | None = None,
    need_semantics: Optional[Dict[str, str]] = None,
) -> Dict[str, List[str]]:
    """Extract key competences from the job description, grouped by need category.
    Returns e.g. {"critical": ["C++", "German"], "nice to have": ["English"], "expected": ["git"]}.
    ``need_categories``: JSON keys to use; order preserved. Default DEFAULT_NEED_SEMANTICS.keys().
    ``need_semantics``: {category: "short description"} for prompt; merged over DEFAULT_NEED_SEMANTICS.
    """
    cats = need_categories or tuple(DEFAULT_NEED_SEMANTICS.keys())  
    semantics = {**DEFAULT_NEED_SEMANTICS, **(need_semantics or {})}
    keys_str = ", ".join(cats)
    example = json.dumps({k: ["C++", "git"] if k == cats[0] else [] for k in cats}, separators=(",", ":"))
    parts = [
        f"{c} = {str(semantics[c]).strip()}"
        for c in cats
        if semantics.get(c) and str(semantics[c]).strip()
    ]
    semantic = (" " + "; ".join(parts) + ". ") if parts else ""
    system = (
        "You are an assistant that extracts key competences or requirements from a job description. "
        f"Return strict JSON with keys exactly: {keys_str}. "
        "Each value is an array of strings (competences). Use empty arrays [] if none in that category. "
        f"Assign each competence to the most appropriate category.{semantic}"
        "Keep each competence short and specific (e.g. 'C++', 'fluent German', 'git'). "
        "Pay attention to separate competences that are ANDed. 'German and English' is ['German', 'English'],  "
        "but 'Object oriented languages like C++ or Java' is a single competence, 'Object oriented programming'. "
        "Do not include intensity modifiers, like 'Good' or 'Fluent'. That goes into the importance."
        "Do not add any other keys or prose."
    )
    prompt = (
        "Job description:\n"
        f"{job_text}\n\n"
        "Respond with JSON only. Example format:\n"
        f"{example}"
    )
    raw = client.call(ModelSize.TINY, system, [prompt])
    _write_trace(trace_dir, system, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    out: Dict[str, List[str]] = {}
    for key in cats:
        val = data.get(key)
        if isinstance(val, list):
            out[key] = [str(x).strip() for x in val if str(x).strip()]
        else:
            out[key] = []
    return out


def _flatten_competences_by_category(
    categories: Dict[str, List[str]],
    category_order: tuple[str, ...] = ("critical", "expected", "nice to have"),
) -> List[tuple[str, str]]:
    """Flatten category dict to [(skill, category), ...] in deterministic order."""
    pairs: List[tuple[str, str]] = []
    seen: set[str] = set()
    for cat in category_order:
        for s in categories.get(cat, []):
            if s and s not in seen:
                seen.add(s)
                pairs.append((s, cat))
    for cat, skills in categories.items():
        if cat in category_order:
            continue
        for s in skills:
            if s and s not in seen:
                seen.add(s)
                pairs.append((s, cat))
    return pairs


@traceable(run_type="chain", name="grade_competence_cv_match")
def grade_competence_cv_match(
    competences: List[str],
    cv_text: str,
    job_text: str,
    client: BaseClient,
    trace_dir: Path | None = None,
    level_labels: tuple[str, ...] | None = None,
) -> Dict[str, str]:
    """Grade each competence as the candidate's level (from CV). Returns {skill: level_label}.
    ``level_labels``: allowed labels; used in prompt and for validation. Default LEVEL_LABELS.
    """
    if not competences:
        return {}
    labels = level_labels or LEVEL_LABELS
    default_label = "Brief experience" if "Brief experience" in labels else labels[len(labels) // 2]

    level_list = ", ".join(labels)
    n = len(labels)
    example_vals = (
        [labels[-1], labels[1], labels[-2], labels[-2]]
        if n >= 3
        else [labels[0]] * 4
    )
    example = dict(zip(["C++", "German", "English", "git"], example_vals[:4]))
    example_str = json.dumps(example, separators=(",", ":"))
    system = (
        "You are an assistant that grades the candidate's level for each competence based on the CV. "
        "Use exactly one of these labels per competence: " + level_list + ". "
        "Be strict; reserve higher-level labels for clear, strong evidence. "
        "Return strict JSON: a single object whose keys are the competences (exactly as given) "
        "and whose values are the level strings. Do not add any other keys or prose."
    )
    prompt = (
        "Key competences (one per line):\n"
        + "\n".join(competences)
        + "\n\n---\n\nCV (excerpt):\n"
        + (cv_text[:12000] if len(cv_text) > 12000 else cv_text)
        + "\n\nAssign each competence one of: " + level_list + ".\n\n"
        "Respond with JSON only. Example format:\n"
        f"{example_str}"
    )
    raw = client.call(ModelSize.TINY, system, [prompt])
    _write_trace(trace_dir, system, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    label_set = frozenset(labels)
    result: Dict[str, str] = {}
    for c in competences:
        v = data.get(c)
        if isinstance(v, str) and v.strip() in label_set:
            result[c] = v.strip()
        else:
            result[c] = default_label
    return result


def _normalize_skill(s: str) -> str:
    """Normalize for matching: strip, lower, collapse spaces."""
    return " ".join((s or "").strip().lower().split())


@traceable(run_type="chain", name="extract_job_metadata")
def extract_job_metadata(
    job_text: str,
    client: BaseClient,
    trace_dir: Path | None = None,
    cv_text: Optional[str] = None,
    scale_config: Optional[Dict[str, Any]] = None,
    existing_competence_ratings: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Extract key job details from the posting.

    If ``cv_text`` is provided, key competences are extracted by category, flattened, then graded
    by candidate level from the CV. Categories and level labels come from ``scale_config`` when
    provided. ``competences`` is {skill: {need, level}}; ``requirements`` is the flat list of skills.

    ``existing_competence_ratings``: {skill: cv_fit 1-5} from profile. If an extracted competence
    matches (strip + case-insensitive), the existing rating is used instead of calling the LLM.
    If all match, grading is skipped.
    """
    need_semantics = {**DEFAULT_NEED_SEMANTICS, **(scale_config.get("needSemantics") or {})} if scale_config else dict(DEFAULT_NEED_SEMANTICS)
    need_labels = tuple(need_semantics.keys())
    level_labels: tuple[str, ...] = LEVEL_LABELS
    if scale_config:
        level_cfg = scale_config.get("level") or {}
        if level_cfg:
            level_labels = tuple(level_cfg.keys())

    if cv_text and str(cv_text).strip():
        base_dir = trace_dir
        no_req_dir = Path(base_dir, "no_requirements") if base_dir else None
        comp_dir = Path(base_dir, "competences") if base_dir else None

        def run_no_requirements():
            return extract_job_metadata_no_requirements(job_text, client, no_req_dir)

        def run_competences():
            return extract_key_competences(
                job_text,
                client,
                comp_dir,
                need_categories=need_labels,
                need_semantics=need_semantics,
            )

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_no = ex.submit(run_no_requirements)
            f_comp = ex.submit(run_competences)
            meta = f_no.result()
            by_category = f_comp.result()

        flat_pairs = _flatten_competences_by_category(
            by_category, category_order=need_labels
        )
        flat_skills = [s for s, _ in flat_pairs]
        default_lvl = "Brief experience" if "Brief experience" in level_labels else level_labels[len(level_labels) // 2]

        # Build lookup: normalized skill -> (original_key, cv_fit 1-5) from existing profile ratings
        existing_lookup: Dict[str, tuple[str, int]] = {}
        if existing_competence_ratings:
            for orig, val in existing_competence_ratings.items():
                if isinstance(val, (int, float)) and 1 <= val <= 5:
                    norm = _normalize_skill(orig)
                    if norm:
                        existing_lookup[norm] = (orig, int(round(val)))

        # Split into matched (use existing) and unmatched (call LLM)
        matched_levels: Dict[str, str] = {}
        unmatched_skills: List[str] = []
        for skill, need in flat_pairs:
            norm = _normalize_skill(skill)
            if norm and norm in existing_lookup:
                _, cv_fit = existing_lookup[norm]
                # Convert numeric 1-5 to level label
                idx = max(0, min(cv_fit - 1, len(level_labels) - 1))
                matched_levels[skill] = level_labels[idx]
            else:
                unmatched_skills.append(skill)

        levels: Dict[str, str] = dict(matched_levels)
        if unmatched_skills:
            grade_dir = Path(base_dir, "grade_cv_match") if base_dir else None
            llm_levels = grade_competence_cv_match(
                unmatched_skills, cv_text, job_text, client, grade_dir, level_labels=level_labels
            )
            for s in unmatched_skills:
                levels[s] = llm_levels.get(s, default_lvl)

        meta["competences"] = {
            skill: {"need": need, "level": levels.get(skill, default_lvl)}
            for skill, need in flat_pairs
        }
        meta["requirements"] = flat_skills
        return meta

    # Legacy single-call path (no CV): extract everything including requirements, no grading.
    system = (
        "You are an assistant that extracts a concise job summary from a job description. "
        "Return strict JSON with these keys: company_name, job_title, location, language, salary, requirements, point_of_contact. "
        "Stick to one language unless it's really mixed. A few english words don't make english a language used."
        "Use null for unknown values. Keep requirements as a short bullet-style list (array of strings). "
        "For point_of_contact, extract if present: name, role (their role in the company), contact_details (email, phone, etc.), and notes (any note about them or how to contact them). "
        "If no point of contact is found, set point_of_contact to null. "
        "Do not add any additional keys or prose."
    )
    prompt = (
        "Job description:\n"
        f"{job_text}\n\n"
        "Respond with JSON only. Example format:\n"
        '{"company_name":"Acme","job_title":"Senior Engineer","location":"Remote","language":"English","salary":"€80-100k","requirements":["Python","AWS"],"point_of_contact":{"name":"John Doe","role":"HR Manager","contact_details":"john.doe@acme.com","notes":"Please contact via email"}}'
    )
    raw = client.call(ModelSize.TINY, system, [prompt])
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        try:
            (trace_dir / "prompt.txt").write_text(f"SYSTEM:\n{system}\n\nPROMPT:\n{prompt}", encoding="utf-8")
            (trace_dir / "raw.txt").write_text(raw, encoding="utf-8")
        except Exception:
            pass

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    requirements = data.get("requirements")
    if isinstance(requirements, list):
        req_list = [str(r).strip() for r in requirements if str(r).strip()]
    elif requirements:
        req_list = [str(requirements).strip()]
    else:
        req_list = []

    poc_data = data.get("point_of_contact")
    point_of_contact = None
    if poc_data and isinstance(poc_data, dict):
        point_of_contact = {
            "name": _clean_metadata_val(poc_data.get("name")),
            "role": _clean_metadata_val(poc_data.get("role")),
            "contact_details": _clean_metadata_val(poc_data.get("contact_details")),
            "notes": _clean_metadata_val(poc_data.get("notes")),
        }
        if not point_of_contact["name"] and not point_of_contact["contact_details"]:
            point_of_contact = None

    return {
        "company_name": _clean_metadata_val(data.get("company_name")),
        "job_title": _clean_metadata_val(data.get("job_title")),
        "location": _clean_metadata_val(data.get("location")),
        "language": _clean_metadata_val(data.get("language")),
        "salary": _clean_metadata_val(data.get("salary")),
        "requirements": req_list,
        "point_of_contact": point_of_contact,
    }

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
            "Focus on what distinguishes the company, in the good and bad. Keep it concise but informative.\n"
            "Do NOT include any links, only plain text.\n"
            "Do NOT just repeat the ads the company puts out. Do report what they say about themselves, "
            "but make it clear it's reporting on how they like to present themselves, not the objective truth. "
            "Be inquisitive, almost cynical, read between the lines. If we are writing to a company that likes "
            "to present themselves as trailblazing but is actually quite boring, or vice versa likes to underpromise "
            "but is actually exceptional, we need to consider both aspects.\n"
        )


@traceable(run_type="chain", name="company_research")
def company_research(company_name: Optional[str], job_text: str, client: BaseClient, trace_dir: Path, additional_company_info: str = "", search: bool = True, model: str | ModelSize = ModelSize.LARGE, search_instructions: str = "") -> Optional[str]:
    """Research company information using OpenAI.
    
    Args:
        company_name: Name of the company to research (may be none if we know the intermediary but not the real one)
        job_text: Job description text
        client: AI client for research
        trace_dir: Directory for tracing
        additional_company_info: User-provided additional context about the company or role
        search: Whether to enable web search tools (default: True)
        model: Model to use (default: ModelSize.LARGE)
        search_instructions: User-provided instructions for how to conduct the background search
    """
    # Use user-provided search instructions or fall back to defaults
    if search_instructions and search_instructions.strip():
        system = search_instructions.strip()
    else:
        system = "You are an expert in searching the internet for information about companies."
    
    company_prompt = ""
    if company_name:
        company_prompt = (
        f"Search the internet and write a short, opinionated company report about {company_name}\n"
        f"To disambiguiate, here is how they present themselves: {job_text[:500]}...\n"
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

    prompt = company_prompt + user_company_context
    if len(prompt) == 0:
        logger.warning("Not enough information to research the company.")
        return None

    result = client.call(model, system, [prompt], search=search)
    (trace_dir / "company_research.txt").write_text(result, encoding="utf-8")
    return result

@traceable(run_type="chain", name="generate_letter")
def generate_letter(cv_text: str, examples: List[dict], company_report: str, job_text: str, client: BaseClient, trace_dir: Path, style_instructions: str = "", additional_user_info: str = "") -> str:
    """Generate a personalized cover letter based on CV, examples, company report, and job description.
    
    Args:
        additional_user_info: User-provided information about themselves relevant to this position (not in CV).
    """
    # Validate CV text is present
    if cv_text is None or not cv_text or not str(cv_text).strip():
        error_msg = "CV text is missing or empty - cannot generate cover letter"
        logger.error(error_msg, extra={"cv_text": cv_text, "cv_text_type": type(cv_text).__name__})
        raise MissingCVError(error_msg)
    
    if not style_instructions:
        style_instructions = get_style_instructions()

    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} [estimated relevance: {ex['score']}/10] - {ex['company_name']} ----\n"
        f"Job Description:\n{ex['job_text']}\n\n"
        f"Cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(examples) if ex['letter_text']
    )
    
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
    
    system = (
        "You are an expert cover letter writer. Using the user's CV, relevant examples of job descriptions "
        "and their corresponding cover letters, the company report, and the target job description, "
        "produce a personalized cover letter in the same style as the examples. Keep it concise (max 1 page).\n"
        "Remember to use the language of THE TARGET JOB DESCRIPTION, even if some or all of the examples might be in a different language. "
        "Use the examples at a higher level: look at style, structure, what is paid attention to, etc.\n"
        + style_instructions
        + additional_context +
        "\n\n"
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Target Job Description:\n" + job_text + "\n=========="
    )
    (trace_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return client.call(ModelSize.XLARGE, system, [prompt])

@traceable(run_type="chain", name="instruction_check")
def instruction_check(letter: str, client: BaseClient, style_instructions: str = "") -> str:
    """Check the letter for consistency with the instructions."""
    if not style_instructions:
        style_instructions = get_style_instructions()

    system = (
        "You are an expert in style and tone. Check the letter for consistency with the style instructions."
        "Be very brief, a couple of sentences is enough. It is likely the instructions were already follwed. "
        "If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Style Instructions:\n" + style_instructions + "\n==========\n\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please catch any strong inconsitency with the instructions, or output NO COMMENT"
    )
    return _call_with_required_suffix(client, ModelSize.TINY, system, prompt)


@traceable(run_type="chain", name="accuracy_check")
def accuracy_check(letter: str, cv_text: str, client: BaseClient, additional_user_info: str = "") -> str:
    """Check the accuracy of the cover letter against the user's CV.
    
    Args:
        additional_user_info: User-provided information about themselves that may explain apparent discrepancies.
    """
    # Build additional context section if user provided info
    additional_context = ""
    if additional_user_info and additional_user_info.strip():
        additional_context = (
            "\n\nIMPORTANT: The user has provided additional information about themselves that is relevant but not in their CV. "
            "Consider this when evaluating accuracy - if a claim is supported by this additional information (e.g., recent certifications, "
            "ongoing learning, planned relocation), it may be acceptable:\n"
            f"User's additional info: {additional_user_info}\n"
        )
    
    system = (
        "You are an expert proofreader. Check the cover letter for factual accuracy against the user's CV. "
        "Look for any claims or statements that are not supported by the CV or are inconsistent with it. "
        "Provide specific feedback on any inaccuracies found. In particular:\n"
        "1. Is what is written in the letter coherent with itself?\n"
        "Examples of incoherhence:  'I am highly expert in Go, I used it once' (using once is not enough to claim experitise), or 'I used Python libraries such as Boost' (Boost is a C++ library)\n"
        "2. Is what is written coherent with the user's CV? Is every claimed expertise supported?"
        "Also pay attention to claims not strictly about tools, they also need to be supported in some way.\n"
        "Example: 'Crypto made me a programmer' [it's a claim, it needs to be supported by the CV]\n"
        "Be especially wary of claims of a 'common thread' or 'throughout my carreer' if it's not supported by the CV.\n"
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
        + additional_context
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for factual accuracy against the CV. "
        "Point out any claims that cannot be verified from the CV or are inconsistent with it."
    )
    return _call_with_required_suffix(client, ModelSize.TINY, system, prompt)

@traceable(run_type="chain", name="precision_check")
def precision_check(letter: str, company_report: str, job_text: str, client: BaseClient) -> str:
    """Check the precision and style of the cover letter against the company report and job description."""
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter addresses the needs of the company, as described in the company report and job description. "
        "1. Were all the requests in the letter addressed, either by claiming and substantiating the necessary competence, or a reasonably substitutable one, or at least ability and willingness to learn in this specific field?\n"
        "Example: 'required: Python, GO' -> 'I have several years of Python experience' [GO is missing]\n"
        "Example: 'required: GO' -> 'while I have not used GO professionally, I have 5 years of C++ experience, and I have follwed a course on GO. When I tried GO on LeetCode, it was easy for me to use' [OK, demonstrates ability to learn]\n"  
        "2. Is there on the contrary any claimed competence that really is superflous, does not adress the explicit or implicit requirements for the job or the company, to the point it makes you wonder if the person understands the job at all?\n"
        "Example: 'we look for a C++ developer' -> 'I have trained several AI models'\n"
        "3. Is there any claim about the company that is not supported by the company report or company information presented in the job offer; or even if it is technically supported, is presented in a way that makes you suspect the writer doesn't understand the company?\n"
        "Example: the company entered crypto last year -> 'excited to apply to a company that has been a pioneer in crypto since its origin' [incorrect, user clearly didn't follow the company for long]\n"
        "Example: the company originated in the F1 racing world, but has pivoted to banking and not worked in racing in a while -> 'excited to enter the world of racing [user is either not up to date on the company, or making up misinterpreting partial information]\n"
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Job Offer:\n" + job_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for consistency with the company report and job description. "
        "Provide specific feedback on how to better align with the company's needs."
    )
    return _call_with_required_suffix(client, ModelSize.TINY, system, prompt)

@traceable(run_type="chain", name="company_fit_check")
def company_fit_check(letter: str, company_report: str, job_offer: str, client: OpenAI) -> str:
    """Check how well the cover letter aligns with the company's values, culture, tone, and needs."""
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter "
        "demonstrates understanding of and alignment with the company's values, mission, tone, and culture "
        "as described in the company report and implied by the job offer.\n"
        "Does the letter feel like it's written for the company? "
        "Does it feel generic, or written with understadnding ad care for what the company does, values, and needs? "
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Job Offer:\n" + job_offer + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for alignment with the company's values, tone, and culture. "
        "Provide feedback on how to better demonstrate understanding of and fit with the company. "
    )
    return _call_with_required_suffix(client, ModelSize.TINY, system, prompt)

@traceable(run_type="chain", name="user_fit_check")
def user_fit_check(letter: str, examples: List[dict], client: OpenAI) -> str:
    """Check how well the cover letter showcases the user's unique value proposition."""
    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} - {ex['company_name']} ----\n"
        f"Cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(examples) if ex['letter_text']
    )
    system = (
        "You are an expert in style and tone. Evaluate how well the cover letter follws the pattern of the previous examples. \n"
        "Does the last letter match the previous ones? Does it look like it's written by the same hand? \n"
        "Does it pay attention to the same aspects? Does it highlight strengths and negotiate weaknesses in the same way? \n"
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for effectiveness in adhering to the style and tone of the previous examples."
        "Provide feedback on how to improve the letter to better match the previous examples."
    )
    return _call_with_required_suffix(client, ModelSize.TINY, system, prompt)

def _format_correction(corr: dict) -> str:
    """Format a correction diff for display in the review agent prompt."""
    corr_type = corr.get("type", "full")
    
    if corr_type == "diff":
        # Compact diff format
        original = corr.get("original", "").strip()
        edited = corr.get("edited", "").strip()
        
        if original or edited:
            return f"  -{original}+{edited}"
        return "  (empty correction)"
    else:
        # Full paragraph format (when >20% changed)
        original = corr.get("original", "").strip()
        edited = corr.get("edited", "").strip()
        return f"  Original: {original}\n  Edited: {edited}"

@traceable(run_type="chain", name="human_check")
def human_check(letter: str, examples: List[dict], client: OpenAI) -> str:
    """Check the letter for consistency with the instructions."""
    rewritten_examples = [
        ex
        for ex in examples
        if ex.get("letter_text") and isinstance(ex.get("ai_letters"), list) and ex["ai_letters"]
    ]
    
    if not rewritten_examples:
        print(f"none of {', '.join(ex.get('company_name','?') for ex in examples)} have AI letters, skipping")
        return "NO COMMENT"

    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} - {ex['company_name']} ----\n"
        "Initial cover letters:\n"
        + "\n\n".join(
            f"[attempt {j+1}]:\n"
            + (f"(Rating: {al.get('rating')}/5)\n" if al.get("rating") else "")
            + (f"(Used chunks: {al.get('chunks_used')})\n" if al.get("chunks_used") is not None else "")
            + (f"(Feedback: \"{al.get('comment')}\")\n" if al.get("comment") else "")
            + f"{al.get('text','')}"
            + (
                "\n\nUser corrections made to this letter:\n" + "\n".join(
                    _format_correction(corr)
                    for corr in (al.get("user_corrections") or [])
                    if isinstance(corr, dict) and (
                        (corr.get("type") == "full" and corr.get("original") is not None and corr.get("edited") is not None) or
                        (corr.get("type") == "diff" and (corr.get("original") is not None or corr.get("edited") is not None))
                    )
                )
                if al.get("user_corrections") else ""
            )
            for j, al in enumerate(ex["ai_letters"])
            if isinstance(al, dict) and al.get("text")
        )
        + "\n\n"
        f"Revised cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(rewritten_examples)
    )
    system = (
        "You are an expert in noticing the patterns behind edits. You will receive a list of examples of job descriptions and corresponding cover letters; "
        "first the cover letter how it was initially written, then the cover letter how a reviewer rewrote it. "
        "The reviewer might have copied parts of the initial letter, or rewrote it from scratch. Either way, pay attention to what was changed. "
        "You might also see ratings, chunk usage counts, explicit feedback comments, and user corrections (compact diffs showing changed portions, or full paragraphs if >20% changed) on the initial letters. "
        "The corrections use a compact format: -original text+edited text for small changes, or full original/edited paragraphs for larger changes. "
        "Use these to understand what the reviewer liked or disliked, and pay special attention to the user corrections as they show exactly what the reviewer changed.\n"
        "Once you noticed what changes tend to be made, flag if in the final, new letter anything looks like a feature than the reviewer would change in the earler examples.\n"
        "Note you should NOT flag elements just for not being in the positive examples, but only if they are present in the initial examples AND usually removed in the revised ones.\n"
        "Be very brief, a couple of sentences is enough. "
        "If at any point you see that nothing in the final letter looks like something the reviewer would change, output NO COMMENT and end the answer. \n"
    )
    prompt = (  
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for anything that looks like something the reviewer would change, based on the examples."
    )
    return _call_with_required_suffix(client, ModelSize.TINY, system, prompt)


@traceable(run_type="chain", name="rewrite_letter")
def rewrite_letter(
    original_letter: str,
    instruction_feedback: str,
    accuracy_feedback: str,
    precision_feedback: str,
    company_fit_feedback: str,
    user_fit_feedback: str,
    human_feedback: str,
    client: OpenAI,
    trace_dir: Path
) -> str:
    """Rewrite the cover letter incorporating all feedback."""
    system = (
        "You are an expert cover letter editor. Given an original cover letter and multiple "
        "pieces of feedback, rewrite the letter to address all concerns while maintaining "
        "its core message and keeping it concise (max 1 page).\n"
    )
    had_feedback = False
    prompt = "========== Original Cover Letter:\n" + original_letter + "\n==========\n"
    if not _is_no_comment(instruction_feedback):
        had_feedback = True
        prompt += "========== Instruction Feedback:\n" + instruction_feedback + "\n==========\n"
    if not _is_no_comment(accuracy_feedback):
        had_feedback = True
        prompt += "========== Accuracy Feedback:\n" + accuracy_feedback + "\n==========\n"
    if not _is_no_comment(precision_feedback):
        had_feedback = True
        prompt += "========== Precision Feedback:\n" + precision_feedback + "\n==========\n"
    if not _is_no_comment(company_fit_feedback):
        had_feedback = True
        prompt += "========== Company Fit Feedback:\n" + company_fit_feedback + "\n==========\n"
    if not _is_no_comment(user_fit_feedback):
        had_feedback = True
        prompt += "========== User Fit Feedback:\n" + user_fit_feedback + "\n==========\n"
    if not _is_no_comment(human_feedback):
        had_feedback = True
        prompt += "========== Human Feedback:\n" + human_feedback + "\n==========\n"
    if not had_feedback:
        print("No feedback provided, returning original letter.")
        return original_letter
    
    prompt += (
        "Please rewrite the cover letter incorporating all the feedback. Output only the revised letter.\n"
        "ONLY address the feedback that was provided. Do not change any part of the letter except what is touched by feedback. \n"
        "Feedback is meant to call attention to specific aspects, but can be short-sighted in context. "
        "If you see that no feedback meaningfully needs to be addressed, output NO REVISIONS and end the answer.\n"
    )
    (trace_dir / "rewrite_prompt.txt").write_text(prompt, encoding="utf-8")
    revised_letter = client.call(ModelSize.XLARGE, system, [prompt])
    if "NO REVISIONS" in revised_letter:
        print("No revisions needed, returning original letter.")
        return original_letter
    return revised_letter 

@traceable(run_type="chain", name="fancy_letter")
def fancy_letter(letter: str, client: OpenAI) -> str:
    """Fancy up the letter with a fancy style."""
    system = (
        "You are an expert in writing cover letters. You will receive a cover letter. "
        "Keep as close to the original as possible, but spell the name of the company with the first letter of each paragraph. "
        "The first paragraph should start with the company name itself. For example:\n"
        "Apple -> 'Apple means excellence... Passion for me is... Pluses of employing me... Leading comes natural to me... Excited to contribute...' "
    )
    prompt = (
        "========== Cover Letter:\n" + letter + "\n==========\n" +
        "Please rewrite the cover letter in a more fancy style. "
    )
    return client.call(ModelSize.XLARGE, system, [prompt])

