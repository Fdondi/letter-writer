"""Job posting extraction, competence grading, and extraction cache."""

import json
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .skill_utils import core_skill_name as _core_skill_name

logger = logging.getLogger(__name__)

_EXTRACTION_CACHE: OrderedDict = OrderedDict()
_EXTRACTION_CACHE_MAX = 64
_EXTRACTION_CACHE_LOCK = Lock()


class MissingCVError(Exception):
    """Catastrophic error: CV text is missing or empty when it should be present."""
    pass


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
    except Exception as e:
        logger.debug("trace write failed: %s", e)


# Shared system for all job-extraction calls. Keeps the prompt prefix identical across
# metadata vs competences so providers (e.g. OpenAI) can reuse cached prefix for the job.
EXTRACTION_SYSTEM = (
    "You are an assistant that extracts structured data from job descriptions. "
    "You will receive a job description and a task. Follow the task exactly. "
    "Respond with JSON only. Do not add any other keys or prose."
)

_JOB_PREFIX = "Job description:\n"


def _job_extraction_cache_prefix(job_text: str) -> str:
    """Single cached block: shared extraction instructions + job text."""
    from .clients.prompt_cache import combine_cache_parts

    return combine_cache_parts(EXTRACTION_SYSTEM, f"{_JOB_PREFIX}{job_text}")


# Structured extraction: single JSON object with competence category arrays plus this string key.
HIRE_PROBLEM_JSON_KEY = "hire_problem"

@traceable(run_type="chain", name="extract_job_metadata_no_requirements")
def extract_job_metadata_no_requirements(
    job_text: str,
    client: BaseClient,
    trace_dir: Path | None = None,
) -> Dict[str, Any]:
    """Extract job metadata except key competences (company, role, location, etc.). No CV needed."""
    task = (
        "Task: Extract the following fields as JSON: company_name, job_title, location, language, salary, point_of_contact. "
        "Stick to one language unless it's really mixed. Use null for unknown values. "
        "For point_of_contact, extract if present: name, role (their role in the company), contact_details (email, phone, etc.), and notes. "
        "If no point of contact is found, set point_of_contact to null."
    )
    example = '{"company_name":"Acme","job_title":"Senior Engineer","location":"Remote","language":"English","salary":"€80-100k","point_of_contact":{"name":"John Doe","role":"HR Manager","contact_details":"john.doe@acme.com","notes":"Please contact via email"}}'
    prompt = f"{task}\n\nRespond with JSON only. Example format:\n{example}"
    cache_block = _job_extraction_cache_prefix(job_text)
    raw = client.call(
        ModelRole.EXTRACTION,
        "",
        [prompt],
        system_cache_prefix=cache_block,
    )
    _write_trace(trace_dir, cache_block, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning("extract_job_metadata JSON parse failed: %s", e)
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
) -> Tuple[Dict[str, List[str]], str]:
    """Extract hire goal/problem plus key competences from the job description in one JSON response.

    Returns ``(competences_by_category, hire_problem)`` where ``hire_problem`` is a short plain-text
    summary of what the company is trying to solve or achieve with this hire (business/team outcome,
    not a skill list). The model must output JSON with key ``hire_problem`` (string) in addition to
    the competence category keys.
    """
    cats = need_categories or tuple(DEFAULT_NEED_SEMANTICS.keys())
    semantics = {**DEFAULT_NEED_SEMANTICS, **(need_semantics or {})}
    keys_str = ", ".join(cats)
    example_obj: Dict[str, Any] = {HIRE_PROBLEM_JSON_KEY: "Grow the payments platform in EU markets while hardening fraud detection."}
    example_obj.update({k: ["C++", "git"] if k == cats[0] else [] for k in cats})
    example = json.dumps(example_obj, separators=(",", ":"))
    parts = [
        f"{c} = {str(semantics[c]).strip()}"
        for c in cats
        if semantics.get(c) and str(semantics[c]).strip()
    ]
    semantic = (" " + "; ".join(parts) + ". ") if parts else ""
    task = (
        f"Task: Respond with a single JSON object. First, set key {HIRE_PROBLEM_JSON_KEY!r} to a concise string (2–6 sentences): "
        "what problem, gap, or outcome the company is hiring this role to address—business or organizational need, not a list of tools. "
        "Infer from the posting; if unclear, give your best inference and briefly note uncertainty.\n"
        f"Second, under these keys exactly—{keys_str}—extract key competences. "
        "Each of those keys maps to an array of strings (competences). Use empty arrays [] if none in that category. "
        f"Assign each competence to the most appropriate category.{semantic}"
        "Output the skill name only, without level or proficiency modifiers: e.g. 'C++', 'German', 'git'. "
        "Do not include words like 'fluent', 'proficient', 'basic', 'language proficiency'—they describe level, not the skill. "
        "Separate competences that are ANDed: 'German and English' is ['German', 'English']. "
        "Single competence for alternatives: 'like C++ or Java' -> one competence."
    )
    prompt = f"{task}\n\nRespond with JSON only. Example format:\n{example}"
    cache_block = _job_extraction_cache_prefix(job_text)
    raw = client.call(
        ModelRole.EXTRACTION,
        "",
        [prompt],
        system_cache_prefix=cache_block,
    )
    _write_trace(trace_dir, cache_block, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning("extract_key_competences JSON parse failed: %s", e)
        data = {}

    hire_raw = data.get(HIRE_PROBLEM_JSON_KEY)
    hire_problem = str(hire_raw).strip() if hire_raw is not None else ""

    out: Dict[str, List[str]] = {}
    for key in cats:
        val = data.get(key)
        if isinstance(val, list):
            core_skills = [_core_skill_name(str(x).strip()) for x in val if str(x).strip()]
            out[key] = [s for s in core_skills if s]
        else:
            out[key] = []
    return out, hire_problem


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
    cv_excerpt = cv_text[:12000] if len(cv_text) > 12000 else cv_text
    from .clients.prompt_cache import combine_cache_parts

    cache_block = combine_cache_parts(
        system,
        f"========== User CV:\n{cv_excerpt}\n==========",
    )
    prompt = (
        "Key competences (one per line):\n"
        + "\n".join(competences)
        + "\n\nAssign each competence one of: " + level_list + ".\n\n"
        "Respond with JSON only. Example format:\n"
        f"{example_str}"
    )
    raw = client.call(ModelRole.EXTRACTION, "", [prompt], system_cache_prefix=cache_block)
    _write_trace(trace_dir, cache_block, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning("score_competences_against_cv JSON parse failed: %s", e)
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


def _level_label_for_rating(level_labels: tuple[str, ...], level_cfg: Dict[str, Any], rating: int) -> str:
    """Map numeric rating (1..5) to the closest configured level label."""
    if not level_labels:
        return "Brief experience"
    target = max(1, min(5, int(rating)))
    if isinstance(level_cfg, dict) and level_cfg:
        best_label = level_labels[0]
        best_delta = float("inf")
        for label in level_labels:
            raw = level_cfg.get(label)
            if isinstance(raw, (int, float)):
                delta = abs(float(raw) - float(target))
                if delta < best_delta:
                    best_delta = delta
                    best_label = label
        if best_delta != float("inf"):
            return best_label
    idx = max(0, min(target - 1, len(level_labels) - 1))
    return level_labels[idx]


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

        cache_key = (job_text, need_labels, frozenset(need_semantics.items()))
        hire_problem = ""
        with _EXTRACTION_CACHE_LOCK:
            if cache_key in _EXTRACTION_CACHE:
                _EXTRACTION_CACHE.move_to_end(cache_key)
                cached = _EXTRACTION_CACHE[cache_key]
                if isinstance(cached, tuple) and len(cached) >= 3:
                    meta, by_category, hire_problem = cached[0], cached[1], str(cached[2] or "")
                elif isinstance(cached, tuple) and len(cached) == 2:
                    meta, by_category = cached[0], cached[1]
                else:
                    meta, by_category = None, None
            else:
                meta, by_category = None, None
        if meta is None or by_category is None:
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
                by_category, hire_problem = f_comp.result()
            with _EXTRACTION_CACHE_LOCK:
                _EXTRACTION_CACHE[cache_key] = (meta, by_category, hire_problem)
                _EXTRACTION_CACHE.move_to_end(cache_key)
                while len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
                    _EXTRACTION_CACHE.popitem(last=False)

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
                # Convert numeric 1-5 to closest configured level label.
                level_map: Dict[str, Any] = (
                    dict(scale_config.get("level") or {}) if scale_config else {}
                )
                matched_levels[skill] = _level_label_for_rating(
                    level_labels, level_map, cv_fit
                )
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
        meta["hire_problem"] = hire_problem or ""
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
        "Respond with JSON only. Example format:\n"
        '{"company_name":"Acme","job_title":"Senior Engineer","location":"Remote","language":"English","salary":"€80-100k","requirements":["Python","AWS"],"point_of_contact":{"name":"John Doe","role":"HR Manager","contact_details":"john.doe@acme.com","notes":"Please contact via email"}}'
    )
    from .clients.prompt_cache import combine_cache_parts

    cache_block = combine_cache_parts(system, f"{_JOB_PREFIX}{job_text}")
    raw = client.call(
        ModelRole.EXTRACTION,
        "",
        [prompt],
        system_cache_prefix=cache_block,
    )
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        try:
            (trace_dir / "prompt.txt").write_text(f"CACHE:\n{cache_block}\n\nPROMPT:\n{prompt}", encoding="utf-8")
            (trace_dir / "raw.txt").write_text(raw, encoding="utf-8")
        except Exception as e:
            logger.debug("trace write failed: %s", e)

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning("extract_job_info JSON parse failed: %s", e)
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
