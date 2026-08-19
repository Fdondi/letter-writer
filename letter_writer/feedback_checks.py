"""Phased and vendor feedback checks, normalization, and agentic context helpers."""

import copy
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .feedback_topics import AGENTIC_TOPIC_KEYS, get_agentic_topic_context_from_registry
from .instructions import get_style_instructions
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

# Material sources: model may emit these only (snippets tied to prompt sections).
FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN = frozenset(
    {"CV", "EXAMPLE", "BACKGROUND_RESEARCH", "LETTER"}
)
# User-added lines from the UI ("Add context"); never emitted by feedback LLMs.
FEEDBACK_CONTEXT_USER_SOURCE = "USER"
# All sources allowed in stored feedback items (material + user).
FEEDBACK_CONTEXT_SOURCES_FROZEN = FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN | frozenset(
    {FEEDBACK_CONTEXT_USER_SOURCE}
)
# JSON schema enums sent to LLMs must not include USER (models would misuse it).
FEEDBACK_CONTEXT_SOURCES_JSON_ENUM = sorted(FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN)


def _user_fit_has_example_letters(top_docs: Optional[Sequence[Any]]) -> bool:
    if not top_docs:
        return False
    for ex in top_docs:
        if (ex.get("letter_text") or "").strip():
            return True
    return False


def _human_has_revision_examples(top_docs: Optional[Sequence[Any]]) -> bool:
    if not top_docs:
        return False
    for ex in top_docs:
        if ex.get("letter_text") and isinstance(ex.get("ai_letters"), list) and (ex.get("ai_letters") or []):
            return True
    return False


def allowed_feedback_context_sources_for_category(
    category: str,
    *,
    top_docs: Optional[Sequence[Any]] = None,
) -> frozenset:
    """Sources that may appear in context_field for this checker (must match prompt sections)."""
    cat = (category or "").strip().lower()
    if cat == "instruction":
        return frozenset({"LETTER", "BACKGROUND_RESEARCH"})
    if cat == "accuracy":
        return frozenset({"CV", "LETTER"})
    if cat in ("precision", "company_fit", "goal_fit"):
        return frozenset({"BACKGROUND_RESEARCH", "LETTER"})
    if cat == "user_fit":
        allowed = frozenset({"CV", "LETTER"})
        if _user_fit_has_example_letters(top_docs):
            allowed = allowed | frozenset({"EXAMPLE"})
        return allowed
    if cat == "human":
        if _human_has_revision_examples(top_docs):
            return frozenset({"EXAMPLE", "LETTER"})
        return frozenset({"LETTER"})
    return frozenset(FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN)


def legacy_context_string_default_source_for_category(
    category: str,
    *,
    top_docs: Optional[Sequence[Any]] = None,
) -> str:
    """Default source for legacy bare-string context lines (must lie in allowed_feedback_context_sources_for_category)."""
    cat = (category or "").strip().lower()
    if cat == "instruction":
        return "BACKGROUND_RESEARCH"
    if cat == "accuracy":
        return "CV"
    if cat in ("precision", "company_fit", "goal_fit"):
        return "BACKGROUND_RESEARCH"
    if cat == "user_fit":
        return "EXAMPLE" if _user_fit_has_example_letters(top_docs) else "CV"
    if cat == "human":
        return "EXAMPLE" if _human_has_revision_examples(top_docs) else "LETTER"
    return "CV"


# In agentic flow, agents may output SKIP or NO COMMENT to leave no feedback
AGENTIC_SKIP_PHRASES = ("NO COMMENT", "SKIP")

VENDOR_FEEDBACK_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "vendor_feedback_items",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "observation": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["ALREADY_GOOD", "PLEASE_FIX"],
                            },
                            "status": {
                                "type": "string",
                                "enum": ["NOT_NEEDED", "SUFFICIENT", "INPUT_NEEDED"],
                            },
                            "context_field": {
                                "type": "object",
                                "properties": {
                                    "items": {
                                        "type": "array",
                                        "items": {
                                            "anyOf": [
                                                {"type": "string"},
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "text": {"type": "string"},
                                                        "source": {
                                                            "type": "string",
                                                            "enum": FEEDBACK_CONTEXT_SOURCES_JSON_ENUM,
                                                        },
                                                    },
                                                    "required": ["text", "source"],
                                                },
                                            ]
                                        },
                                    }
                                },
                                "required": ["items"],
                            },
                            # Only used when status == INPUT_NEEDED. UI forces user to fill before approval.
                            "user_context": {"type": "string"},
                            # Optional template / hint for the user. Shown as placeholder in UI input.
                            "user_instructions": {"type": "string"},
                        },
                        "required": ["observation", "type"],
                    },
                },
            },
            "required": ["items"],
        },
    },
}


def _extract_json_value(raw: str) -> Any:
    """Parse JSON from model output, tolerating fenced blocks."""
    text = (raw or "").strip()
    if not text:
        raise json.JSONDecodeError("empty", text, 0)
    if text.startswith("```"):
        lines = text.split("\n")
        inner = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
        text = inner.strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return json.loads(text)


def normalize_parsed_feedback_items(
    data: Any,
    *,
    allowed_context_sources: frozenset,
    legacy_string_source: str = "CV",
) -> List[Dict[str, Any]]:
    """Normalize parsed JSON (object with items, or bare list) into feedback item dicts."""
    raw_items: List[Any] = []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        raw_items = data["items"]
    elif isinstance(data, list):
        raw_items = data
    out: List[Dict[str, Any]] = []
    input_needed_count = 0
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        obs = str(it.get("observation", "")).strip()
        typ = str(it.get("type", "")).strip().upper()
        if typ not in ("ALREADY_GOOD", "PLEASE_FIX"):
            continue
        if typ == "PLEASE_FIX" and not obs:
            continue
        if typ == "ALREADY_GOOD" and not obs:
            continue
        status = str(it.get("status") or "").strip().upper()
        if status not in ("NOT_NEEDED", "SUFFICIENT", "INPUT_NEEDED"):
            status = "NOT_NEEDED"

        allowed = allowed_context_sources & FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN
        if not allowed:
            allowed = frozenset(FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN)

        context_items: List[Dict[str, str]] = []
        cf = it.get("context_field")
        if isinstance(cf, dict) and isinstance(cf.get("items"), list):
            for raw in (cf.get("items", []) or []):
                if isinstance(raw, str):
                    t = raw.strip()
                    if t and legacy_string_source in allowed:
                        context_items.append({"text": t, "source": legacy_string_source})
                    continue
                if isinstance(raw, dict):
                    t = str(raw.get("text") or "").strip()
                    src = str(raw.get("source") or "").strip().upper()
                    if not t:
                        continue
                    if src not in allowed:
                        continue
                    context_items.append({"text": t, "source": src})

        # Enforce status invariants (do not drop item; just normalize field).
        if status == "NOT_NEEDED":
            context_items = []
        elif status == "SUFFICIENT":
            if not context_items:
                status = "NOT_NEEDED"
        # INPUT_NEEDED: context_items optional.
        if status == "INPUT_NEEDED":
            input_needed_count += 1
            # Hard reject: too many user-input requests. Raise to trigger retry.
            if input_needed_count > 2:
                raise ValueError("Too many INPUT_NEEDED items (hard max 2)")

        # Do not let models pre-fill user_context; this field is for the user to supply.
        # Keep it empty even if the model emits it.
        user_context = ""
        user_instructions = str(it.get("user_instructions") or "").strip()
        if status != "INPUT_NEEDED":
            user_instructions = ""

        out.append(
            {
                "id": str(uuid.uuid4()),
                "observation": obs,
                "type": typ,
                "status": status,
                "context_field": {"items": context_items},
                "user_context": user_context,
                "user_instructions": user_instructions,
            }
        )
    return out

KNOWN_WEAKNESSES_FEEDBACK_RULES = (
    "\n\nKnown weaknesses rules (when the block above is non-empty):\n"
    "- These are objective requirement gaps that CANNOT be fixed by obtaining the credential mid-application "
    "(missing mandatory certifications, language level below the posting, years-of-experience shortfalls, etc.). "
    "Assume the applicant is aware and may bet on transferable skills or willingness to learn.\n"
    "- Do NOT emit PLEASE_FIX asking to obtain the missing credential, raise a language level overnight, invent "
    "experience, or otherwise pretend the gap can be closed.\n"
    "- A gap counts as honestly addressed only when the letter acknowledges the real shortfall and argues around it "
    "with truthful framing (transferable skills, adjacent experience, concrete learning plan) — without inflating or "
    "mislabeling qualifications.\n"
    "- ALWAYS emit PLEASE_FIX when the letter misrepresents a known weakness, even if the topic is mentioned. "
    "This includes inflated labels (e.g. calling B2 'fluent'), incompatible pairs (e.g. 'fluent German (B2)'), "
    "implying the requirement is met when known_weaknesses says it is not, or silent omission with no honest "
    "compensating argument.\n"
    "- Mentioning a gap is not enough if the wording is dishonest or equivocating. Accuracy or precision critiques "
    "that catch false fluency, false certification, or inflated experience on a known weakness must stay as PLEASE_FIX.\n"
    "- If the letter honestly frames the gap, omit it or mark ALREADY_GOOD — never turn honest framing into an "
    "action item.\n"
)
def format_known_weaknesses_block(known_weaknesses: Optional[Sequence[Dict[str, Any]]]) -> str:
    """Context block injected into feedback prompts when objective gaps were pre-identified."""
    if not known_weaknesses:
        return ""
    lines: List[str] = []
    for i, w in enumerate(known_weaknesses, 1):
        if not isinstance(w, dict):
            continue
        req = str(w.get("requirement", "")).strip()
        gap = str(w.get("gap", "")).strip()
        if req and gap:
            lines.append(f"{i}. Requirement: {req} | Applicant gap: {gap}")
        elif req:
            lines.append(f"{i}. {req}")
        elif gap:
            lines.append(f"{i}. {gap}")
    if not lines:
        return ""
    return (
        "\n\n========== Known weaknesses (objective gaps the applicant cannot fix; they are aware and chose to apply anyway) ==========\n"
        + "\n".join(lines)
        + "\n==========\n"
    )


@traceable(run_type="chain", name="call_vendor_feedback_items")
def _call_vendor_feedback_items(
    client: BaseClient,
    model_role: ModelRole,
    system: str,
    prompt: str,
    *,
    allowed_context_sources: frozenset,
    legacy_string_source: str = "CV",
    search: bool = False,
    max_retries: int = 2,
    system_cache_prefix: Optional[str] = None,
    prompt_cache_key: Optional[str] = None,
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Call an LLM; response must be JSON with an items array of {observation, type}."""
    allowed = allowed_context_sources & FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN
    if not allowed:
        allowed = frozenset(FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN)
    allowed_sorted = ", ".join(sorted(allowed))
    response_schema = vendor_feedback_json_schema_for_allowed_sources(allowed)
    common_instructions = (
        " Reply with JSON only. The answer must be an object with key \"items\" whose value is an array. "
        "Each array element must be {\"observation\": string, \"type\": either \"ALREADY_GOOD\" or \"PLEASE_FIX\"}. "
        "Emit one element per distinct observation, each item should be logically a bullet point. "
        "ALREADY_GOOD is meant as an escape hatch for when you realize after writing that the observation does not actually demand an action. "
        "Prefer marking as ALREADY_GOOD to producing irrelevant PLEASE_FIX, but do not aim to write ALREADY_GOOD points. "
        "If there is nothing substantive to critique, that's great, emit an empty items array. Avoid padding with nitpicks or non-problems. "
        "Include all the needed information, since the reviewer will ONLY see your comment, don't assume they have additional information. "
        "For example, 'include concrete metrics/examples' is not a good observation; if you have metrics or examples include them explicitly. "
        "If you don't have the data that would be needed, it is not available. Suggest ways of working around this absence instead.\n\n"
        "Optional enrichment fields per item (use them to avoid vague feedback):\n"
        "- \"status\": one of NOT_NEEDED | SUFFICIENT | INPUT_NEEDED.\n"
        "- \"context_field\": {\"items\": [{\"text\": string, \"source\": string}, ...]} — use ONLY objects with \"source\", never bare strings.\n"
        "- \"user_context\": string (only when status=INPUT_NEEDED).\n"
        "Rules for context_field.items[].source (must match where the snippet came from in THIS prompt):\n"
        "- CV: quoted or summarized from a \"User CV\" / \"========== User CV\" section, or from \"User's additional info\" when that block is present.\n"
        "- EXAMPLE: from \"Reference Examples\" / prior cover letters in the examples section.\n"
        "- LETTER: from \"Cover Letter to Check\" / the current draft only.\n"
        "- BACKGROUND_RESEARCH: from company report, job offer, and/or style instructions when those sections appear in this prompt.\n"
        "Never label a snippet from reference letters as CV, or vice versa. If you are unsure of the origin, omit the snippet.\n"
        f"Hard constraint for THIS check: each context_field item's \"source\" must be exactly one of: {allowed_sorted}. "
        "Do not use any other source label.\n"
        "Rules:\n"
        "1) context_field.items is NOT for talking to the user. It must contain only neutral, paste-ready snippets extracted from your context "
        "(verbatim quotes when possible, otherwise short faithful paraphrases/summaries). Each item should read like something that can be dropped into a cover letter.\n"
        "2) Do not add headings like 'Vorschläge' / 'suggestion:' / 'you should...' / imperatives in context_field.items. No instructions, no meta commentary.\n"
        "2b) context_field.items should usually be empty. Optimum count is 0. Maximum recommended is 1.\n"
        "2c) Do not cite or invent 'reference examples'. Only refer to reference examples if they were explicitly included in your input. "
        "If you want to propose sample phrasing but it is NOT a quote/paraphrase from your provided context, put it in user_instructions (not context_field.items).\n"
        "3) If your observation depends on specific concrete facts you CAN SEE in your context (numbers, dates, named projects, tools, outcomes, scope, etc.), "
        "set status=SUFFICIENT and include those facts in context_field.items.\n"
        "2) If your observation does NOT need extra facts (it is fully actionable as written), set status=NOT_NEEDED and set context_field.items to [].\n"
        "4) If your observation would require facts you DO NOT HAVE (despite the instruction above), set status=INPUT_NEEDED and write the observation as a precise request for input "
        "(what exact info is missing, why it matters, and a minimal template the user can fill). Put that template into user_instructions (for the UI placeholder). You may leave context_field.items empty.\n"
        "4b) User-input requests (status=INPUT_NEEDED) should usually be zero. Optimum count is 0. Maximum recommended is 1. Hard maximum is 2. Never exceed 2 INPUT_NEEDED items in total.\n"
        "4c) If the issue is missing factual content (e.g. languages) and you cannot quote it from your context, it is INPUT_NEEDED. "
        "If it is purely a stylistic preference and no new facts are required, it is NOT_NEEDED.\n"
        "4) Do NOT write generic requests like 'add metrics' or 'add examples' unless you can provide the concrete metrics/examples in context_field.items (SUFFICIENT) \n"
        "Never invent facts."
    )
    kw_block = format_known_weaknesses_block(known_weaknesses)
    kw_rules = KNOWN_WEAKNESSES_FEEDBACK_RULES if kw_block else ""
    enforced_system = system + common_instructions + kw_rules
    enforced_prompt = prompt + kw_block
    from .clients.prompt_cache import cache_key_for_prefix

    resolved_cache_key = prompt_cache_key or (
        cache_key_for_prefix(system_cache_prefix, fallback="")
        if system_cache_prefix
        else None
    )

    last_raw = ""
    for attempt in range(1, max_retries + 1):
        try:
            last_raw = client.call(
                model_role,
                enforced_system,
                [enforced_prompt],
                search=search,
                response_format=response_schema,
                system_cache_prefix=system_cache_prefix,
                prompt_cache_key=resolved_cache_key or None,
            )
            data = _extract_json_value(last_raw)
            items = normalize_parsed_feedback_items(
                data,
                allowed_context_sources=allowed,
                legacy_string_source=legacy_string_source,
            )
            return items
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(
                "Vendor feedback JSON parse failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                e,
            )
        except Exception as e:
            logger.warning(
                "Vendor feedback LLM call failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                e,
            )

    logger.warning("Vendor feedback falling back to empty list after failed parses")
    return []


MISSING_CONTEXT_ITEMS_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "missing_feedback_context_items",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "source": {
                                "type": "string",
                                "enum": FEEDBACK_CONTEXT_SOURCES_JSON_ENUM,
                            },
                        },
                        "required": ["text", "source"],
                    },
                }
            },
            "required": ["items"],
        },
    },
}


def vendor_feedback_json_schema_for_allowed_sources(allowed: frozenset) -> Dict[str, Any]:
    """Copy of VENDOR_FEEDBACK_JSON_SCHEMA with context source enum restricted to ``allowed``."""
    sch = copy.deepcopy(VENDOR_FEEDBACK_JSON_SCHEMA)
    enum_list = sorted(allowed & FEEDBACK_CONTEXT_SOURCES_FROZEN)
    if not enum_list:
        enum_list = list(FEEDBACK_CONTEXT_SOURCES_JSON_ENUM)
    target = sch["json_schema"]["schema"]["properties"]["items"]["items"]["properties"]["context_field"]["properties"][
        "items"
    ]["items"]["anyOf"][1]["properties"]["source"]
    target["enum"] = enum_list
    return sch


def missing_context_items_schema_for_allowed_sources(allowed: frozenset) -> Dict[str, Any]:
    sch = copy.deepcopy(MISSING_CONTEXT_ITEMS_SCHEMA)
    enum_list = sorted(allowed & FEEDBACK_CONTEXT_SOURCES_FROZEN)
    if not enum_list:
        enum_list = list(FEEDBACK_CONTEXT_SOURCES_JSON_ENUM)
    sch["json_schema"]["schema"]["properties"]["items"]["items"]["properties"]["source"]["enum"] = enum_list
    return sch
# Keys must match phased feedback buckets; sourced from feedback_topics registry.
PHASED_FEEDBACK_CATEGORY_KEYS = AGENTIC_TOPIC_KEYS

def _phased_feedback_checker_instruction_prompts(
    *,
    letter: str,
    style_instructions: str,
) -> Tuple[str, str]:
    si = style_instructions or get_style_instructions()
    system = (
        "You are an expert in style and tone. Check the letter for consistency with the style instructions. "
        "Keep each observation brief. Report only concrete mismatches or omissions, not praise.\n"
    )
    prompt = "List any strong inconsistencies with the instructions, or use empty items if none."
    return system, prompt


def _instruction_check_context(*, style_instructions: str, letter: str) -> str:
    """Cached context block for instruction_check (style instructions + letter)."""
    si = style_instructions or get_style_instructions()
    return (
        "========== Style Instructions:\n" + si + "\n==========\n\n"
        "========== Cover Letter to Check:\n" + letter + "\n=========="
    )


def _phased_feedback_checker_accuracy_prompts(
    *,
    letter: str,
    cv_text: str,
    additional_user_info: str,
) -> Tuple[str, str]:
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
        "3. If known_weaknesses are listed in context, flag misrepresentation: inflated labels (fluent for B2), "
        "incompatible pairs ('fluent German (B2)'), or implying a requirement is met when the gap block says otherwise.\n"
        "Example: 'Crypto made me a programmer' [it's a claim, it needs to be supported by the CV]\n"
        "Be especially wary of claims of a 'common thread' or 'throughout my carreer' if it's not supported by the CV.\n"
        "Keep each observation brief; no praise or reassurance. If there is no meaningful issue, return an empty items list.\n"
        + additional_context
    )
    prompt = "Review factual accuracy against the CV. Point out claims that cannot be verified or are inconsistent."
    return system, prompt


def _cv_letter_context(*, cv_text: str, letter: str) -> str:
    """Cached context block for accuracy_check and user_fit_check (Group 2).

    Both checks pass this as ``system_cache_prefix`` so they share the same
    Anthropic cache entry when called with the same CV and letter.
    """
    cv_block = (cv_text or "").strip() or "(No CV text was provided in this session.)"
    return (
        "========== User CV:\n" + cv_block + "\n==========\n"
        "========== Cover Letter to Check:\n" + letter + "\n=========="
    )


def _company_job_letter_context(
    *,
    company_report: str,
    job_text: str,
    letter: str,
) -> str:
    """Cached context block for precision_check and company_fit_check (Group 1).

    Both checks pass this as ``system_cache_prefix`` so they share the same
    Anthropic cache entry when called with the same company report, job, and letter.
    """
    return (
        "========== Company Report:\n" + company_report + "\n==========\n"
        "========== Job Offer:\n" + job_text + "\n==========\n"
        "========== Cover Letter to Check:\n" + letter + "\n=========="
    )


def _company_job_hire_goal_letter_context(
    *,
    company_report: str,
    job_text: str,
    letter: str,
    hire_problem: str = "",
) -> str:
    """Like ``_company_job_letter_context`` plus optional extracted hire-goal line for goal_fit_check."""
    hp = (hire_problem or "").strip()
    prefix = ""
    if hp:
        prefix = (
            "========== Hire goal / problem this role solves (structured extraction from the posting):\n"
            + hp
            + "\n==========\n"
        )
    return prefix + _company_job_letter_context(
        company_report=company_report, job_text=job_text, letter=letter
    )


def _phased_feedback_checker_precision_prompts(
    *,
    letter: str,
    company_report: str,
    job_text: str,
) -> Tuple[str, str]:
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter addresses the needs of the company, as described in the company report and job description. "
        "1. Were all the requests in the letter addressed, either by claiming and substantiating the necessary competence, or a reasonably substitutable one, or at least ability and willingness to learn in this specific field?\n"
        "When known_weaknesses are listed in context, honest framing of a gap counts as addressed; dishonest framing does not — "
        "e.g. 'fluent German (B2)' or calling B2 fluent when the job requires fluency is a PLEASE_FIX, not acceptable coverage.\n"
        "Example: 'required: Python, GO' -> 'I have several years of Python experience' [GO is missing]\n"
        "Example: 'required: GO' -> 'while I have not used GO professionally, I have 5 years of C++ experience, and I have follwed a course on GO. When I tried GO on LeetCode, it was easy for me to use' [OK, demonstrates ability to learn]\n"
        "2. Is there on the contrary any claimed competence that really is superflous, does not adress the explicit or implicit requirements for the job or the company, to the point it makes you wonder if the person understands the job at all?\n"
        "Example: 'we look for a C++ developer' -> 'I have trained several AI models'\n"
        "3. Is there any claim about the company that is not supported by the company report or company information presented in the job offer; or even if it is technically supported, is presented in a way that makes you suspect the writer doesn't understand the company?\n"
        "Example: the company entered crypto last year -> 'excited to apply to a company that has been a pioneer in crypto since its origin' [incorrect, user clearly didn't follow the company for long]\n"
        "Example: the company originated in the F1 racing world, but has pivoted to banking and not worked in racing in a while -> 'excited to enter the world of racing [user is either not up to date on the company, or making up misinterpreting partial information]\n"
        "Keep each observation brief; do not praise coverage or fit. If there is no meaningful issue, return an empty items list.\n"
    )
    prompt = "Review consistency with the company report and job description; note misalignment or superfluous claims."
    return system, prompt


def _phased_feedback_checker_company_fit_prompts(
    *,
    letter: str,
    company_report: str,
    job_text: str,
) -> Tuple[str, str]:
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter "
        "demonstrates understanding of and alignment with the company's values, mission, tone, and culture "
        "as described in the company report and implied by the job offer.\n"
        "Focus on generic, shallow, or mismatched signals—not on affirming that the letter is personalized. "
        "Keep each observation brief. If there is no meaningful issue, return an empty items list.\n"
    )
    prompt = "Review alignment with the company's values, tone, and culture; note generic or mismatched content."
    return system, prompt


def _phased_feedback_checker_goal_fit_prompts(
    *,
    letter: str,
    company_report: str,
    job_text: str,
    hire_problem: str = "",
) -> Tuple[str, str]:
    hp = (hire_problem or "").strip()
    framing = (
        "A separate field (shown in context as 'Hire goal / problem this role solves') states what problem or outcome "
        "the company is trying to address with this hire. Treat that as the primary reading of the hiring intent when it is non-empty; "
        "otherwise infer the hiring goal only from the job offer and company report.\n"
        if hp
        else "Infer what problem or outcome the company is trying to address with this hire from the job offer and company report.\n"
    )
    system = (
        "You are a senior hiring manager. Evaluate whether the cover letter reads like someone who understands "
        "what the company is trying to solve or achieve with this hire, and sounds ready to contribute toward that—"
        "whether through relevant experience, credible ability and willingness to learn in the right areas, and/or "
        "the right mindset (ownership, clarity, collaboration, pragmatism) where the posting calls for it.\n"
        + framing
        + "Do not nitpick wording if the substance shows engagement with the hiring goal. "
        "Flag only meaningful gaps: the letter ignores the central problem, focuses on unrelated bragging, "
        "misreads what the role is for, or sounds like a generic template with no line of sight to the company's need.\n"
        "Keep each observation brief. If there is no meaningful issue, return an empty items list.\n"
    )
    prompt = (
        "Review whether the letter demonstrates understanding of the hiring goal and readiness to help solve it."
    )
    return system, prompt


def _phased_feedback_checker_user_fit_prompts(
    *,
    letter: str,
    cv_text: str,
    additional_user_info: str,
    top_docs: Optional[Sequence[TopDocument]],
) -> Tuple[str, str]:
    examples = top_docs or ()
    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} - {ex['company_name']} ----\n"
        f"Cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(examples) if ex.get("letter_text")
    )
    if not examples_formatted.strip():
        examples_formatted = "(No reference letters available.)"
    additional_block = ""
    if additional_user_info and additional_user_info.strip():
        additional_block = (
            "\n\n========== User's additional info (relevant but not fully captured in CV):\n"
            + additional_user_info.strip()
            + "\n==========\n"
        )
    system = (
        "You are an expert in style and tone. The goal is continuity of voice: the draft should feel like the same author "
        "as the reference letters (register, rhythm, how strengths and caveats are framed, paragraph logic, level of directness).\n"
        "Reference letters are different applications: they will mention different companies, projects, and emphases. "
        "That is expected. Do NOT treat \"the examples bring up topic X but this draft does not\" as a problem by itself, "
        "even if X is a strength in the CV—omission is fine when this role does not call for it.\n"
        "Use the CV and optional additional info only to flag factual gaps: claims or implications in the draft that conflict with, "
        "or undersell without reason, facts that are clearly stated there (languages, degrees, dates, tools, etc.). "
        "Do not ask the draft to repeat biographical detail from the examples that is absent from the CV/additional info unless "
        "the issue is stylistic (e.g. the draft suddenly reads unlike those examples).\n"
        "Flag divergences in tone, structure, emphasis, or how weaknesses are handled compared with the references—not missing topics "
        "that simply differ between applications.\n"
        "Do not praise imitation or \"good fit\" with the examples; only output items where the draft should change.\n"
        "Keep each observation brief. If there is no meaningful issue, return an empty items list.\n"
        "NOTE: The reference examples are prior cover letters written by/about the SAME applicant. "
        "If the difference is that some information isn't provided, any factual claims that appear in the reference examples may be used. \n"
        "When you attach context_field snippets, tag sources correctly: EXAMPLE for reference letters; LETTER for the draft under "
        "\"Cover Letter to Check\"; CV for the User CV block and for the User's additional info block (both are authoritative facts about the applicant).\n"
    )
    prompt = (
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n"
        + additional_block
        + "\nCompare to the reference letters and CV. Note where the draft diverges in voice (same-hand cues), structure, emphasis, "
        "or handling of weaknesses versus the examples, or where it misuses or omits facts that clearly matter given the CV/additional info. "
        "Do not demand topic overlap with the examples."
    )
    return system, prompt


def _format_human_check_examples(
    top_docs: Optional[Sequence[TopDocument]],
) -> Optional[str]:
    """Format rewritten examples for human_check; returns None if none exist.

    Extracted so both the prompt builder and the context builder can use the
    same formatted string without duplicating the filtering and formatting logic.
    """
    examples = top_docs or ()
    rewritten_examples = [
        ex
        for ex in examples
        if ex.get("letter_text") and isinstance(ex.get("ai_letters"), list) and ex["ai_letters"]
    ]
    if not rewritten_examples:
        return None
    return "\n\n".join(
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


def _phased_feedback_checker_human_prompts(
    *,
    letter: str,
    top_docs: Optional[Sequence[TopDocument]],
) -> Optional[Tuple[str, str]]:
    """Returns (system, prompt), or None if there are no rewritten examples."""
    if _format_human_check_examples(top_docs) is None:
        return None
    system = (
        "You are an expert in noticing the patterns behind edits. You will receive a list of examples of job descriptions and corresponding cover letters; "
        "first the cover letter how it was initially written, then the cover letter how a reviewer rewrote it. "
        "The reviewer might have copied parts of the initial letter, or rewrote it from scratch. Either way, pay attention to what was changed. "
        "You might also see ratings, chunk usage counts, explicit feedback comments, and user corrections (compact diffs showing changed portions, or full paragraphs if >20% changed) on the initial letters. "
        "The corrections use a compact format: -original text+edited text for small changes, or full original/edited paragraphs for larger changes. "
        "Use these to understand what the reviewer changed and removed, and pay special attention to user corrections.\n"
        "Once you notice recurring removals or rewrites, flag if the new letter contains similar content the reviewer would likely change.\n"
        "Do NOT flag elements merely for not appearing in references, and do not output praise—only actionable mismatches with edit patterns.\n"
        "Do NOT flag mismatches just for existing. Ask yourself: is this difference relevant to the new job? "
        "Example: all letters mention German proficiency because German is required or implied, but the new job is clearly in English only -> not relevant. "
        "Or: all letters are highly formal, but the new company is proud of their informal culture -> not relevant. "
        "Keep each observation brief. If nothing in the draft matches a pattern the reviewer would change, return empty items.\n"
    )
    prompt = "Flag anything in the draft that resembles content the reviewer typically removes or rewrites in the examples."
    return system, prompt


def _human_check_context(*, top_docs: Optional[Sequence[TopDocument]], letter: str) -> str:
    """Cached context block for human_check (rich examples + letter)."""
    examples_formatted = _format_human_check_examples(top_docs) or "(No reference examples.)"
    return (
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n"
        "========== Cover Letter to Check:\n" + letter + "\n=========="
    )


def _normalize_missing_context_items_payload(
    data: Any,
    *,
    allowed_context_sources: frozenset,
    legacy_string_source: str = "CV",
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(data, dict):
        return out
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return out
    allowed = allowed_context_sources & FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN
    if not allowed:
        allowed = frozenset(FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN)
    for raw in raw_items:
        if isinstance(raw, str):
            t = raw.strip()
            if t and legacy_string_source in allowed:
                out.append({"text": t, "source": legacy_string_source})
            continue
        if isinstance(raw, dict):
            t = str(raw.get("text") or "").strip()
            src = str(raw.get("source") or "").strip().upper()
            if not t:
                continue
            if src not in allowed:
                continue
            out.append({"text": t, "source": src})
    return out


@traceable(run_type="chain", name="suggest_additional_feedback_context")
def _run_suggest_additional_feedback_context(
    client: BaseClient,
    category: str,
    observation: str,
    existing_context_items: Sequence[Any],
    system: str,
    base_prompt: str,
    *,
    top_docs: Optional[Sequence[TopDocument]] = None,
) -> List[Dict[str, str]]:
    """Follow-up LLM pass: snippets for context_field using the same materials as the checker prompt above."""
    allowed = allowed_feedback_context_sources_for_category(category, top_docs=top_docs)
    legacy = legacy_context_string_default_source_for_category(category, top_docs=top_docs)
    allowed_sorted = ", ".join(sorted(allowed))
    existing_texts: List[str] = []
    for raw in existing_context_items or []:
        if isinstance(raw, dict):
            t = str(raw.get("text") or "").strip()
        else:
            t = str(raw or "").strip()
        if t:
            existing_texts.append(t)
    existing_block = "\n".join(f"- {t}" for t in existing_texts) if existing_texts else "(none)"
    task = (
        "\n\n========== Task (follow-up; same materials as above) ==========\n"
        "One critique was already produced about this cover letter (below). "
        "The first pass may have omitted useful paste-ready snippets drawn from the SAME materials you see above.\n\n"
        f"Critique:\n{(observation or '').strip()}\n\n"
        f"Snippets already attached to this critique (do not repeat or lightly rephrase):\n{existing_block}\n\n"
        'Reply with JSON only: an object {"items": [...]} where each element is '
        '{"text": string, "source": <one of allowed values>}. '
        f"The only allowed \"source\" values for this category are: {allowed_sorted}. "
        "Include ONLY additional snippets from the materials in this conversation "
        "(verbatim quotes or short faithful paraphrases). "
        'Return {"items": []} if nothing new is available. Never invent facts.\n'
    )
    full_prompt = base_prompt + task
    ctx_schema = missing_context_items_schema_for_allowed_sources(allowed)
    raw = client.call(
        ModelRole.FEEDBACK_CONTEXT,
        system,
        [full_prompt],
        response_format=ctx_schema,
    )
    try:
        data = _extract_json_value(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return _normalize_missing_context_items_payload(
        data,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
    )


def _legacy_feedback_string_to_items(val: str) -> List[Dict[str, Any]]:
    """Convert legacy suffix-style feedback strings to structured items."""
    t = (val or "").strip()
    if not t:
        return []
    u = t.upper()
    if u.endswith("NO COMMENT") or u.endswith("SKIP"):
        return []
    if u.endswith("PLEASE FIX"):
        obs = t[: -len("PLEASE FIX")].rstrip()
        if not obs:
            return []
        return [{"id": str(uuid.uuid4()), "observation": obs, "type": "PLEASE_FIX"}]
    return [{"id": str(uuid.uuid4()), "observation": t, "type": "PLEASE_FIX"}]


def normalize_feedback_value(
    val: Any,
    *,
    category_key: str,
    top_docs: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Normalize feedback stored for one dimension (list, legacy string, or empty)."""
    if val is None:
        return []
    allowed = allowed_feedback_context_sources_for_category(category_key, top_docs=top_docs)
    legacy = legacy_context_string_default_source_for_category(category_key, top_docs=top_docs)
    if isinstance(val, list):
        out: List[Dict[str, Any]] = []
        for it in val:
            if not isinstance(it, dict):
                continue
            obs = str(it.get("observation", "")).strip()
            typ = str(it.get("type", "")).strip().upper()
            if typ not in ("ALREADY_GOOD", "PLEASE_FIX"):
                continue
            if typ == "PLEASE_FIX" and not obs:
                continue
            if typ == "ALREADY_GOOD" and not obs:
                continue
            iid = str(it.get("id") or "").strip()
            if not iid:
                iid = str(uuid.uuid4())
            status = str(it.get("status") or "").strip().upper()
            if status not in ("NOT_NEEDED", "SUFFICIENT", "INPUT_NEEDED"):
                status = "NOT_NEEDED"

            context_items: List[Dict[str, Any]] = []
            cf = it.get("context_field")
            if isinstance(cf, dict) and isinstance(cf.get("items"), list):
                for raw in (cf.get("items", []) or []):
                    if isinstance(raw, str):
                        t = raw.strip()
                        if t and legacy in allowed:
                            context_items.append({"text": t, "source": legacy})
                        continue
                    if isinstance(raw, dict):
                        src = str(raw.get("source") or "").strip().upper()
                        if src not in FEEDBACK_CONTEXT_SOURCES_FROZEN:
                            continue
                        if src != FEEDBACK_CONTEXT_USER_SOURCE and src not in allowed:
                            continue
                        is_user = src == FEEDBACK_CONTEXT_USER_SOURCE
                        if is_user:
                            t = str(raw.get("text") or "")
                        else:
                            t = str(raw.get("text") or "").strip()
                            if not t:
                                continue
                        row: Dict[str, Any] = {"text": t, "source": src}
                        if is_user:
                            p = raw.get("persist_to_cv")
                            row["persist_to_cv"] = True if p is None else bool(p)
                        context_items.append(row)
            if status == "NOT_NEEDED":
                context_items = []
            elif status == "SUFFICIENT":
                if not context_items:
                    status = "NOT_NEEDED"

            user_context = str(it.get("user_context") or "").strip()
            user_instructions = str(it.get("user_instructions") or "").strip()
            if status != "INPUT_NEEDED":
                user_context = ""
                user_instructions = ""
            input_declined = bool(it.get("input_declined")) if status == "INPUT_NEEDED" else False
            persist_uc = it.get("persist_user_context_to_cv")
            if persist_uc is None:
                persist_uc = True
            else:
                persist_uc = bool(persist_uc)
            persist_ua = it.get("persist_user_context_for_agents")
            if persist_ua is None:
                persist_ua = persist_uc
            else:
                persist_ua = bool(persist_ua)
            if status != "INPUT_NEEDED":
                input_declined = False

            row = {
                "id": iid,
                "observation": obs,
                "type": typ,
                "status": status,
                "context_field": {"items": context_items},
                "user_context": user_context,
                "user_instructions": user_instructions,
                "input_declined": input_declined,
                "persist_user_context_to_cv": persist_uc,
                "persist_user_context_for_agents": persist_ua,
            }
            dg = str(it.get("duplicate_group_id") or "").strip()
            if dg:
                row["duplicate_group_id"] = dg
            ick = str(it.get("input_cluster_key") or "").strip()
            if ick:
                row["input_cluster_key"] = ick
            out.append(row)
        return out
    if isinstance(val, str):
        return _legacy_feedback_string_to_items(val)
    return []


def normalize_feedback_map(
    fb: Optional[Dict[str, Any]],
    top_docs: Optional[Sequence[Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Normalize a full feedback dict (all phased dimensions) after load or override."""
    keys = ("instruction", "accuracy", "precision", "company_fit", "goal_fit", "user_fit", "human")
    src = fb or {}
    return {
        k: normalize_feedback_value(src.get(k), category_key=k, top_docs=top_docs)
        for k in keys
    }


def _is_no_comment(feedback: str) -> bool:
    """Return True only if feedback explicitly ends with NO COMMENT."""
    return (feedback or "").strip().upper().endswith("NO COMMENT")
def is_agentic_skip(text: str) -> bool:
    """Return True if the agent chose to skip leaving feedback (NO COMMENT or SKIP)."""
    normalized = (text or "").strip().upper()
    return any(normalized.endswith(p) for p in AGENTIC_SKIP_PHRASES)
def instruction_check(
    letter: str,
    client: BaseClient,
    style_instructions: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check the letter for consistency with the instructions."""
    si = style_instructions or get_style_instructions()
    system, prompt = _phased_feedback_checker_instruction_prompts(letter=letter, style_instructions=si)
    allowed = allowed_feedback_context_sources_for_category("instruction")
    legacy = legacy_context_string_default_source_for_category("instruction")
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_instruction_check_context(style_instructions=si, letter=letter),
        known_weaknesses=known_weaknesses,
    )


@traceable(run_type="chain", name="accuracy_check")
def accuracy_check(
    letter: str,
    cv_text: str,
    client: BaseClient,
    additional_user_info: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check the accuracy of the cover letter against the user's CV.

    Args:
        additional_user_info: User-provided information about themselves that may explain apparent discrepancies.
    """
    system, prompt = _phased_feedback_checker_accuracy_prompts(
        letter=letter,
        cv_text=cv_text,
        additional_user_info=additional_user_info,
    )
    allowed = allowed_feedback_context_sources_for_category("accuracy")
    legacy = legacy_context_string_default_source_for_category("accuracy")
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_cv_letter_context(cv_text=cv_text, letter=letter),
        known_weaknesses=known_weaknesses,
    )

@traceable(run_type="chain", name="precision_check")
def precision_check(
    letter: str,
    company_report: str,
    job_text: str,
    client: BaseClient,
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check the precision and style of the cover letter against the company report and job description."""
    system, prompt = _phased_feedback_checker_precision_prompts(
        letter=letter,
        company_report=company_report,
        job_text=job_text,
    )
    allowed = allowed_feedback_context_sources_for_category("precision")
    legacy = legacy_context_string_default_source_for_category("precision")
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_company_job_letter_context(
            company_report=company_report, job_text=job_text, letter=letter
        ),
        known_weaknesses=known_weaknesses,
    )

@traceable(run_type="chain", name="company_fit_check")
def company_fit_check(
    letter: str,
    company_report: str,
    job_offer: str,
    client: BaseClient,
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check how well the cover letter aligns with the company's values, culture, tone, and needs."""
    system, prompt = _phased_feedback_checker_company_fit_prompts(
        letter=letter,
        company_report=company_report,
        job_text=job_offer,
    )
    allowed = allowed_feedback_context_sources_for_category("company_fit")
    legacy = legacy_context_string_default_source_for_category("company_fit")
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_company_job_letter_context(
            company_report=company_report, job_text=job_offer, letter=letter
        ),
        known_weaknesses=known_weaknesses,
    )

@traceable(run_type="chain", name="goal_fit_check")
def goal_fit_check(
    letter: str,
    company_report: str,
    job_offer: str,
    client: BaseClient,
    hire_problem: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check whether the letter shows understanding of the hiring goal and readiness to contribute."""
    system, prompt = _phased_feedback_checker_goal_fit_prompts(
        letter=letter,
        company_report=company_report,
        job_text=job_offer,
        hire_problem=hire_problem,
    )
    allowed = allowed_feedback_context_sources_for_category("goal_fit")
    legacy = legacy_context_string_default_source_for_category("goal_fit")
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_company_job_hire_goal_letter_context(
            company_report=company_report,
            job_text=job_offer,
            letter=letter,
            hire_problem=hire_problem,
        ),
        known_weaknesses=known_weaknesses,
    )

@traceable(run_type="chain", name="user_fit_check")
def user_fit_check(
    letter: str,
    examples: Sequence[TopDocument],
    client: BaseClient,
    cv_text: str = "",
    additional_user_info: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check how well the cover letter showcases the user's unique value proposition."""
    system, prompt = _phased_feedback_checker_user_fit_prompts(
        letter=letter,
        top_docs=examples,
        cv_text=cv_text,
        additional_user_info=additional_user_info,
    )
    allowed = allowed_feedback_context_sources_for_category("user_fit", top_docs=examples)
    legacy = legacy_context_string_default_source_for_category("user_fit", top_docs=examples)
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_cv_letter_context(cv_text=cv_text, letter=letter),
        known_weaknesses=known_weaknesses,
    )

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

@traceable(run_type="chain", name="run_phased_feedback_checks")
def run_phased_feedback_checks(
    *,
    draft_letter: str,
    cv_text: str,
    company_report: str,
    job_text: str,
    top_docs: Sequence[TopDocument],
    client: BaseClient,
    style_instructions: str = "",
    additional_user_info: str = "",
    hire_problem: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Run all draft feedback checks with cache-aware scheduling.

    Checks that share the same ``system_cache_prefix`` run sequentially so
    providers bill one cache write and subsequent reads at the discount rate.
    """
    from .clients.prompt_cache import run_cache_grouped_tasks

    si = style_instructions or get_style_instructions()
    company_job_ctx = _company_job_letter_context(
        company_report=company_report, job_text=job_text, letter=draft_letter
    )
    cv_letter_ctx = _cv_letter_context(cv_text=cv_text, letter=draft_letter)
    instruction_ctx = _instruction_check_context(style_instructions=si, letter=draft_letter)
    goal_ctx = _company_job_hire_goal_letter_context(
        company_report=company_report,
        job_text=job_text,
        letter=draft_letter,
        hire_problem=hire_problem,
    )
    human_ctx = _human_check_context(top_docs=top_docs, letter=draft_letter)

    tasks: List[Tuple[str, Optional[str], Any]] = [
        (
            "instruction",
            instruction_ctx,
            lambda: instruction_check(draft_letter, client, si, known_weaknesses),
        ),
        (
            "accuracy",
            cv_letter_ctx,
            lambda: accuracy_check(
                draft_letter, cv_text, client, additional_user_info, known_weaknesses
            ),
        ),
        (
            "precision",
            company_job_ctx,
            lambda: precision_check(
                draft_letter, company_report, job_text, client, known_weaknesses
            ),
        ),
        (
            "company_fit",
            company_job_ctx,
            lambda: company_fit_check(
                draft_letter, company_report, job_text, client, known_weaknesses
            ),
        ),
        (
            "goal_fit",
            goal_ctx,
            lambda: goal_fit_check(
                draft_letter,
                company_report,
                job_text,
                client,
                hire_problem,
                known_weaknesses,
            ),
        ),
        (
            "user_fit",
            cv_letter_ctx,
            lambda: user_fit_check(
                draft_letter,
                top_docs,
                client,
                cv_text,
                additional_user_info,
                known_weaknesses,
            ),
        ),
        (
            "human",
            human_ctx,
            lambda: human_check(draft_letter, top_docs, client, known_weaknesses),
        ),
    ]

    results = run_cache_grouped_tasks(tasks, max_parallel_groups=7)
    return {
        "instruction": results.get("instruction") or [],
        "accuracy": results.get("accuracy") or [],
        "precision": results.get("precision") or [],
        "company_fit": results.get("company_fit") or [],
        "goal_fit": results.get("goal_fit") or [],
        "user_fit": results.get("user_fit") or [],
        "human": results.get("human") or [],
    }


@traceable(run_type="chain", name="human_check")
def human_check(
    letter: str,
    examples: Sequence[TopDocument],
    client: BaseClient,
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Check the letter against human-rewritten example patterns."""
    prompts = _phased_feedback_checker_human_prompts(letter=letter, top_docs=examples)
    if prompts is None:
        logger.info(
            "none of %s have AI letters, skipping",
            ", ".join(ex.get("company_name", "?") for ex in examples),
        )
        return []
    system, prompt = prompts
    allowed = allowed_feedback_context_sources_for_category("human", top_docs=examples)
    legacy = legacy_context_string_default_source_for_category("human", top_docs=examples)
    return _call_vendor_feedback_items(
        client,
        ModelRole.FEEDBACK,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
        system_cache_prefix=_human_check_context(top_docs=examples, letter=letter),
        known_weaknesses=known_weaknesses,
    )


def _letter_block_for_context(draft_letter: str) -> str:
    """Single draft: one block."""
    return "========== Cover Letter (draft):\n" + draft_letter + "\n==========\n\n"


def _letter_block_multi_proposals(draft_letters: dict) -> str:
    """Multiple drafts (one per vendor): present as proposals for comparison and preference."""
    if not draft_letters:
        return "========== Cover Letter (draft):\n(No proposals.)\n==========\n\n"
    parts = ["========== Cover letter proposals (one per vendor). Compare them; you may suggest edits to one or say you prefer one vendor's choice over another.\n"]
    for vendor, text in draft_letters.items():
        parts.append(f"--- Proposal ({vendor}) ---\n" + (text or "") + "\n")
    parts.append("==========\n\n")
    return "\n".join(parts)


def get_agentic_topic_context(
    topic: str,
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
    If draft_letters is provided (vendor -> text), multiple proposals are shown so agents can compare and prefer one vendor's choice.
    """
    return get_agentic_topic_context_from_registry(
        topic,
        draft_letter=draft_letter,
        cv_text=cv_text,
        company_report=company_report,
        job_text=job_text,
        top_docs=top_docs,
        style_instructions=style_instructions,
        additional_user_info=additional_user_info,
        draft_letters=draft_letters,
        hire_problem=hire_problem,
    )


# ---------------------------------------------------------------------------
# Public API (prefer these over underscore-prefixed helpers in new code)
# ---------------------------------------------------------------------------

phased_feedback_checker_instruction_prompts = _phased_feedback_checker_instruction_prompts
phased_feedback_checker_accuracy_prompts = _phased_feedback_checker_accuracy_prompts
phased_feedback_checker_precision_prompts = _phased_feedback_checker_precision_prompts
phased_feedback_checker_company_fit_prompts = _phased_feedback_checker_company_fit_prompts
phased_feedback_checker_goal_fit_prompts = _phased_feedback_checker_goal_fit_prompts
phased_feedback_checker_user_fit_prompts = _phased_feedback_checker_user_fit_prompts
phased_feedback_checker_human_prompts = _phased_feedback_checker_human_prompts
run_suggest_additional_feedback_context = _run_suggest_additional_feedback_context


def get_phased_feedback_checker_prompts(
    category: str,
    *,
    letter: str,
    style_instructions: str = "",
    cv_text: str = "",
    additional_user_info: str = "",
    company_report: str = "",
    job_text: str = "",
    hire_problem: str = "",
    top_docs: Optional[Sequence[TopDocument]] = None,
) -> Optional[Tuple[str, str]]:
    """Return (system, prompt) for a phased feedback category using the topic registry."""
    from .feedback_topics import get_topic_config

    cat = (category or "").strip().lower()
    get_topic_config(cat)
    if cat == "instruction":
        return phased_feedback_checker_instruction_prompts(
            letter=letter, style_instructions=style_instructions
        )
    if cat == "accuracy":
        return phased_feedback_checker_accuracy_prompts(
            letter=letter, cv_text=cv_text, additional_user_info=additional_user_info
        )
    if cat == "precision":
        return phased_feedback_checker_precision_prompts(
            letter=letter, company_report=company_report, job_text=job_text
        )
    if cat == "company_fit":
        return phased_feedback_checker_company_fit_prompts(
            letter=letter, company_report=company_report, job_text=job_text
        )
    if cat == "goal_fit":
        return phased_feedback_checker_goal_fit_prompts(
            letter=letter,
            company_report=company_report,
            job_text=job_text,
            hire_problem=hire_problem,
        )
    if cat == "user_fit":
        return phased_feedback_checker_user_fit_prompts(
            letter=letter,
            cv_text=cv_text,
            additional_user_info=additional_user_info,
            top_docs=top_docs,
        )
    if cat == "human":
        return phased_feedback_checker_human_prompts(letter=letter, top_docs=top_docs)
    raise KeyError(f"Unknown feedback category: {category!r}")
