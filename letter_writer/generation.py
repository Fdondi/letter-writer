import copy
import json
import logging
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pathlib import Path
from langsmith import traceable

from .config import TRACE_DIR, get_extraction_model
from .clients.base import BaseClient, ModelSize
from .skill_utils import core_skill_name as _core_skill_name
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

# In-memory cache for job extraction (no_requirements + key_competences) to avoid
# repeated LLM calls when the same job is processed multiple times (e.g. multiple CVs).
# Key: (job_text, need_labels, need_semantics_frozen). LRU eviction when at capacity.
_EXTRACTION_CACHE: OrderedDict = OrderedDict()
_EXTRACTION_CACHE_MAX = 64
_EXTRACTION_CACHE_LOCK = Lock()


class MissingCVError(Exception):
    """Catastrophic error: CV text is missing or empty when it should be present."""
    pass

# Allowed values for feedback context_field.items[].source (API + UI must stay aligned).
FEEDBACK_CONTEXT_SOURCES_FROZEN = frozenset(
    {"CV", "EXAMPLE", "BACKGROUND_RESEARCH", "LETTER"}
)
FEEDBACK_CONTEXT_SOURCES_JSON_ENUM = sorted(FEEDBACK_CONTEXT_SOURCES_FROZEN)


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
    if cat in ("precision", "company_fit"):
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
    return frozenset(FEEDBACK_CONTEXT_SOURCES_FROZEN)


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
    if cat in ("precision", "company_fit"):
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

# Topic keys for per-topic agentic feedback.
# Order matters: downstream topics can review and challenge prior topics' top comments.
AGENTIC_TOPIC_KEYS = ("instruction", "company_fit", "precision", "user_fit", "human", "accuracy")


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

        allowed = allowed_context_sources & FEEDBACK_CONTEXT_SOURCES_FROZEN
        if not allowed:
            allowed = frozenset(FEEDBACK_CONTEXT_SOURCES_FROZEN)

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


@traceable(run_type="chain", name="call_vendor_feedback_items")
def _call_vendor_feedback_items(
    client: BaseClient,
    model_size: ModelSize,
    system: str,
    prompt: str,
    *,
    allowed_context_sources: frozenset,
    legacy_string_source: str = "CV",
    search: bool = False,
    max_retries: int = 2,
) -> List[Dict[str, Any]]:
    """Call an LLM; response must be JSON with an items array of {observation, type}."""
    allowed = allowed_context_sources & FEEDBACK_CONTEXT_SOURCES_FROZEN
    if not allowed:
        allowed = frozenset(FEEDBACK_CONTEXT_SOURCES_FROZEN)
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
    enforced_system = system + common_instructions

    last_raw = ""
    for attempt in range(1, max_retries + 1):
        try:
            last_raw = client.call(
                model_size,
                enforced_system,
                [prompt],
                search=search,
                response_format=response_schema,
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


# Keys must match phased feedback buckets (instruction, accuracy, …).
PHASED_FEEDBACK_CATEGORY_KEYS = (
    "instruction",
    "accuracy",
    "precision",
    "company_fit",
    "user_fit",
    "human",
)


def build_phased_feedback_checker_prompts(
    category: str,
    *,
    letter: str,
    style_instructions: str = "",
    cv_text: str = "",
    additional_user_info: str = "",
    company_report: str = "",
    job_text: str = "",
    top_docs: Optional[Sequence[TopDocument]] = None,
) -> Optional[Tuple[str, str]]:
    """Same (system, user_prompt) as the corresponding *check* LLM, or None if that dimension is skipped (human: no AI examples)."""
    cat = (category or "").strip().lower()
    if cat not in PHASED_FEEDBACK_CATEGORY_KEYS:
        raise ValueError(f"Unknown feedback category: {category}")

    if cat == "instruction":
        si = style_instructions or get_style_instructions()
        system = (
            "You are an expert in style and tone. Check the letter for consistency with the style instructions. "
            "Keep each observation brief. Report only concrete mismatches or omissions, not praise.\n"
        )
        prompt = (
            "========== Style Instructions:\n" + si + "\n==========\n\n" +
            "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
            "List any strong inconsistencies with the instructions, or use empty items if none."
        )
        return system, prompt

    if cat == "accuracy":
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
            "Keep each observation brief; no praise or reassurance. If there is no meaningful issue, return an empty items list.\n"
            + additional_context
        )
        prompt = (
            "========== User CV:\n" + cv_text + "\n==========\n" +
            "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
            "Review factual accuracy against the CV. Point out claims that cannot be verified or are inconsistent."
        )
        return system, prompt

    if cat == "precision":
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
            "Keep each observation brief; do not praise coverage or fit. If there is no meaningful issue, return an empty items list.\n"
        )
        prompt = (
            "========== Company Report:\n" + company_report + "\n==========\n" +
            "========== Job Offer:\n" + job_text + "\n==========\n" +
            "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
            "Review consistency with the company report and job description; note misalignment or superfluous claims."
        )
        return system, prompt

    if cat == "company_fit":
        system = (
            "You are a senior HR manager at the company. Evaluate how well the cover letter "
            "demonstrates understanding of and alignment with the company's values, mission, tone, and culture "
            "as described in the company report and implied by the job offer.\n"
            "Focus on generic, shallow, or mismatched signals—not on affirming that the letter is personalized. "
            "Keep each observation brief. If there is no meaningful issue, return an empty items list.\n"
        )
        prompt = (
            "========== Company Report:\n" + company_report + "\n==========\n" +
            "========== Job Offer:\n" + job_text + "\n==========\n" +
            "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
            "Review alignment with the company's values, tone, and culture; note generic or mismatched content."
        )
        return system, prompt

    if cat == "user_fit":
        examples = top_docs or ()
        examples_formatted = "\n\n".join(
            f"---- Example #{i+1} - {ex['company_name']} ----\n"
            f"Cover Letter:\n{ex['letter_text']}\n\n"
            for i, ex in enumerate(examples) if ex.get("letter_text")
        )
        if not examples_formatted.strip():
            examples_formatted = "(No reference letters available.)"
        cv_block = (cv_text or "").strip()
        if not cv_block:
            cv_block = "(No CV text was provided in this session.)"
        additional_block = ""
        if additional_user_info and additional_user_info.strip():
            additional_block = (
                "\n\n========== User's additional info (relevant but not fully captured in CV):\n"
                + additional_user_info.strip()
                + "\n==========\n"
            )
        system = (
            "You are an expert in style and tone. Evaluate how well the cover letter follows the pattern of the previous examples. \n"
            "You also have the applicant's CV (and optional additional info): use it to judge whether factual content "
            "(languages, degrees, dates, tools, etc.) is missing from the draft when it exists in the CV, or only appeared in older letters.\n"
            "Flag divergences: tone, structure, emphasis, or how weaknesses are handled compared with the references. \n"
            "Do not praise imitation or \"good fit\" with the examples; only output items where the draft should change.\n"
            "Keep each observation brief. If there is no meaningful issue, return an empty items list.\n"
            "NOTE: The reference examples are prior cover letters written by/about the SAME applicant. "
            "If the difference is that some information isn't provided, any factual claims that appear in the reference examples may be used. \n"
            "When you attach context_field snippets, tag sources correctly: EXAMPLE for reference letters; LETTER for the draft under "
            "\"Cover Letter to Check\"; CV for the User CV block and for the User's additional info block (both are authoritative facts about the applicant).\n"
        )
        prompt = (
            "========== Reference Examples:\n" + examples_formatted + "\n==========\n\n"
            "========== User CV:\n" + cv_block + "\n==========\n"
            + additional_block
            + "\n========== Cover Letter to Check:\n" + letter + "\n==========\n\n"
            "Compare to the reference letters and CV; note where the draft diverges in style, emphasis, handling of weaknesses, or omits relevant facts from the CV."
        )
        return system, prompt

    if cat == "human":
        examples = top_docs or ()
        rewritten_examples = [
            ex
            for ex in examples
            if ex.get("letter_text") and isinstance(ex.get("ai_letters"), list) and ex["ai_letters"]
        ]
        if not rewritten_examples:
            return None
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
            "Use these to understand what the reviewer changed and removed, and pay special attention to user corrections.\n"
            "Once you notice recurring removals or rewrites, flag if the new letter contains similar content the reviewer would likely change.\n"
            "Do NOT flag elements merely for not appearing in references, and do not output praise—only actionable mismatches with edit patterns.\n"
            "Keep each observation brief. If nothing in the draft matches a pattern the reviewer would change, return empty items.\n"
        )
        prompt = (
            "========== Reference Examples:\n" + examples_formatted + "\n==========\n" +
            "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
            "Flag anything in the draft that resembles content the reviewer typically removes or rewrites in the examples."
        )
        return system, prompt

    raise ValueError(f"Unknown feedback category: {category}")


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
    allowed = allowed_context_sources & FEEDBACK_CONTEXT_SOURCES_FROZEN
    if not allowed:
        allowed = frozenset(FEEDBACK_CONTEXT_SOURCES_FROZEN)
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


@traceable(run_type="chain", name="suggest_additional_feedback_context_items")
def suggest_additional_feedback_context_items(
    client: BaseClient,
    category: str,
    observation: str,
    existing_context_items: Sequence[Any],
    *,
    letter: str,
    style_instructions: str = "",
    cv_text: str = "",
    additional_user_info: str = "",
    company_report: str = "",
    job_text: str = "",
    top_docs: Optional[Sequence[TopDocument]] = None,
) -> List[Dict[str, str]]:
    """
    Second pass: same checker materials as the original feedback call, focused on finding
    paste-ready snippets that belong with this observation but were omitted from context_field.
    """
    base = build_phased_feedback_checker_prompts(
        category,
        letter=letter,
        style_instructions=style_instructions,
        cv_text=cv_text,
        additional_user_info=additional_user_info,
        company_report=company_report,
        job_text=job_text,
        top_docs=top_docs,
    )
    if base is None:
        raise ValueError(
            "The human-dimension checker has no reference materials (no AI letter examples with revision history)."
        )
    system, base_prompt = base
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
        ModelSize.TINY,
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

            context_items: List[Dict[str, str]] = []
            cf = it.get("context_field")
            if isinstance(cf, dict) and isinstance(cf.get("items"), list):
                for raw in (cf.get("items", []) or []):
                    if isinstance(raw, str):
                        t = raw.strip()
                        if t and legacy in allowed:
                            context_items.append({"text": t, "source": legacy})
                        continue
                    if isinstance(raw, dict):
                        t = str(raw.get("text") or "").strip()
                        src = str(raw.get("source") or "").strip().upper()
                        if not t:
                            continue
                        if src not in FEEDBACK_CONTEXT_SOURCES_FROZEN:
                            continue
                        if src not in allowed:
                            continue
                        context_items.append({"text": t, "source": src})
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
    """Normalize a full six-key (or partial) feedback dict after load or override."""
    keys = ("instruction", "accuracy", "precision", "company_fit", "user_fit", "human")
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


def _get_extraction_model_name() -> str:
    """Resolve model used for extraction-style calls."""
    return get_extraction_model()


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
    prompt = f"{_JOB_PREFIX}{job_text}\n\n{task}\n\nRespond with JSON only. Example format:\n{example}"
    raw = client.call(_get_extraction_model_name(), EXTRACTION_SYSTEM, [prompt])
    _write_trace(trace_dir, EXTRACTION_SYSTEM, prompt, raw)

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
    task = (
        f"Task: Extract key competences as JSON with keys exactly: {keys_str}. "
        "Each value is an array of strings (competences). Use empty arrays [] if none in that category. "
        f"Assign each competence to the most appropriate category.{semantic}"
        "Output the skill name only, without level or proficiency modifiers: e.g. 'C++', 'German', 'git'. "
        "Do not include words like 'fluent', 'proficient', 'basic', 'language proficiency'—they describe level, not the skill. "
        "Separate competences that are ANDed: 'German and English' is ['German', 'English']. "
        "Single competence for alternatives: 'like C++ or Java' -> one competence."
    )
    prompt = f"{_JOB_PREFIX}{job_text}\n\n{task}\n\nRespond with JSON only. Example format:\n{example}"
    raw = client.call(_get_extraction_model_name(), EXTRACTION_SYSTEM, [prompt])
    _write_trace(trace_dir, EXTRACTION_SYSTEM, prompt, raw)

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning("extract_key_competences JSON parse failed: %s", e)
        data = {}

    out: Dict[str, List[str]] = {}
    for key in cats:
        val = data.get(key)
        if isinstance(val, list):
            core_skills = [_core_skill_name(str(x).strip()) for x in val if str(x).strip()]
            out[key] = [s for s in core_skills if s]
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
    raw = client.call(_get_extraction_model_name(), system, [prompt])
    _write_trace(trace_dir, system, prompt, raw)

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
        with _EXTRACTION_CACHE_LOCK:
            if cache_key in _EXTRACTION_CACHE:
                _EXTRACTION_CACHE.move_to_end(cache_key)
                meta, by_category = _EXTRACTION_CACHE[cache_key]
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
                by_category = f_comp.result()
            with _EXTRACTION_CACHE_LOCK:
                _EXTRACTION_CACHE[cache_key] = (meta, by_category)
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
    raw = client.call(_get_extraction_model_name(), system, [prompt])
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        try:
            (trace_dir / "prompt.txt").write_text(f"SYSTEM:\n{system}\n\nPROMPT:\n{prompt}", encoding="utf-8")
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
def company_research(
    company_name: Optional[str],
    job_text: str,
    client: BaseClient,
    trace_dir: Path,
    additional_company_info: str = "",
    search: bool = True,
    model: str | ModelSize = ModelSize.LARGE,
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
        model: Model to use (default: ModelSize.LARGE)
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
        # #region agent log
        try:
            import json
            with open("/home/fdondi/Documents/#GitHub/letter-writer/.cursor/debug-5b1b21.log", "a") as _f:
                _f.write(json.dumps({"sessionId": "5b1b21", "hypothesisId": "H1", "location": "generation.py:company_research", "message": "company_research returning None (empty prompt)", "data": {"company_name": company_name, "job_text_is_none": job_text is None}, "timestamp": __import__("time").time() * 1000}) + "\n")
        except Exception as e:
            logger.debug("trace write failed: %s", e)
        # #endregion
        return None

    result = client.call(model, system, [prompt], search=search)
    (trace_dir / "company_research.txt").write_text(result, encoding="utf-8")
    # #region agent log
    try:
        import json
        with open("/home/fdondi/Documents/#GitHub/letter-writer/.cursor/debug-5b1b21.log", "a") as _f:
            _f.write(json.dumps({"sessionId": "5b1b21", "hypothesisId": "H1", "location": "generation.py:company_research", "message": "company_research return", "data": {"result_is_none": result is None, "result_type": type(result).__name__}, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception as e:
        logger.debug("trace write failed: %s", e)
    # #endregion
    return result

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
) -> str:
    """Generate a personalized cover letter based on CV, examples, company report, and job description.
    
    Args:
        additional_user_info: User-provided information about themselves relevant to this position (not in CV).
    """
    # #region agent log
    try:
        import json
        with open("/home/fdondi/Documents/#GitHub/letter-writer/.cursor/debug-5b1b21.log", "a") as _f:
            _f.write(json.dumps({"sessionId": "5b1b21", "hypothesisId": "H3", "location": "generation.py:generate_letter", "message": "generate_letter entry", "data": {"company_report_is_none": company_report is None, "job_text_is_none": job_text is None, "company_report_type": type(company_report).__name__, "job_text_type": type(job_text).__name__}, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception as e:
        logger.debug("trace write failed: %s", e)
    # #endregion
    company_report = company_report if company_report is not None else ""
    job_text = job_text if job_text is not None else ""
    # Validate CV text is present
    if cv_text is None or not cv_text or not str(cv_text).strip():
        error_msg = "CV text is missing or empty - cannot generate cover letter"
        logger.error(error_msg, extra={"cv_text": cv_text, "cv_text_type": type(cv_text).__name__})
        raise MissingCVError(error_msg)
    
    if not style_instructions:
        style_instructions = get_style_instructions()

    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} [estimated relevance: {ex.get('score', 0)}/10] - {ex.get('company_name', '')} ----\n"
        f"Job Description:\n{ex.get('job_text', '')}\n\n"
        f"Cover Letter:\n{ex.get('letter_text', '')}\n\n"
        for i, ex in enumerate(examples) if (ex.get("letter_text") or "").strip()
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
    # #region agent log
    try:
        import json
        with open("/home/fdondi/Documents/#GitHub/letter-writer/.cursor/debug-5b1b21.log", "a") as _f:
            _f.write(json.dumps({"sessionId": "5b1b21", "hypothesisId": "H3", "location": "generation.py:generate_letter:before_prompt", "message": "before prompt build", "data": {"company_report_is_none": company_report is None, "job_text_is_none": job_text is None}, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception as e:
        logger.debug("trace write failed: %s", e)
    # #endregion
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Target Job Description:\n" + job_text + "\n=========="
    )
    (trace_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return client.call(ModelSize.XLARGE, system, [prompt])

@traceable(run_type="chain", name="instruction_check")
def instruction_check(letter: str, client: BaseClient, style_instructions: str = "") -> List[Dict[str, Any]]:
    """Check the letter for consistency with the instructions."""
    si = style_instructions or get_style_instructions()
    prompts = build_phased_feedback_checker_prompts(
        "instruction", letter=letter, style_instructions=si
    )
    assert prompts is not None
    system, prompt = prompts
    allowed = allowed_feedback_context_sources_for_category("instruction")
    legacy = legacy_context_string_default_source_for_category("instruction")
    return _call_vendor_feedback_items(
        client,
        ModelSize.TINY,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
    )


@traceable(run_type="chain", name="accuracy_check")
def accuracy_check(letter: str, cv_text: str, client: BaseClient, additional_user_info: str = "") -> List[Dict[str, Any]]:
    """Check the accuracy of the cover letter against the user's CV.
    
    Args:
        additional_user_info: User-provided information about themselves that may explain apparent discrepancies.
    """
    prompts = build_phased_feedback_checker_prompts(
        "accuracy",
        letter=letter,
        cv_text=cv_text,
        additional_user_info=additional_user_info,
    )
    assert prompts is not None
    system, prompt = prompts
    allowed = allowed_feedback_context_sources_for_category("accuracy")
    legacy = legacy_context_string_default_source_for_category("accuracy")
    return _call_vendor_feedback_items(
        client,
        ModelSize.TINY,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
    )

@traceable(run_type="chain", name="precision_check")
def precision_check(letter: str, company_report: str, job_text: str, client: BaseClient) -> List[Dict[str, Any]]:
    """Check the precision and style of the cover letter against the company report and job description."""
    prompts = build_phased_feedback_checker_prompts(
        "precision",
        letter=letter,
        company_report=company_report,
        job_text=job_text,
    )
    assert prompts is not None
    system, prompt = prompts
    allowed = allowed_feedback_context_sources_for_category("precision")
    legacy = legacy_context_string_default_source_for_category("precision")
    return _call_vendor_feedback_items(
        client,
        ModelSize.TINY,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
    )

@traceable(run_type="chain", name="company_fit_check")
def company_fit_check(letter: str, company_report: str, job_offer: str, client: BaseClient) -> List[Dict[str, Any]]:
    """Check how well the cover letter aligns with the company's values, culture, tone, and needs."""
    prompts = build_phased_feedback_checker_prompts(
        "company_fit",
        letter=letter,
        company_report=company_report,
        job_text=job_offer,
    )
    assert prompts is not None
    system, prompt = prompts
    allowed = allowed_feedback_context_sources_for_category("company_fit")
    legacy = legacy_context_string_default_source_for_category("company_fit")
    return _call_vendor_feedback_items(
        client,
        ModelSize.TINY,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
    )

@traceable(run_type="chain", name="user_fit_check")
def user_fit_check(
    letter: str,
    examples: Sequence[TopDocument],
    client: BaseClient,
    cv_text: str = "",
    additional_user_info: str = "",
) -> List[Dict[str, Any]]:
    """Check how well the cover letter showcases the user's unique value proposition."""
    prompts = build_phased_feedback_checker_prompts(
        "user_fit",
        letter=letter,
        top_docs=examples,
        cv_text=cv_text,
        additional_user_info=additional_user_info,
    )
    assert prompts is not None
    system, prompt = prompts
    allowed = allowed_feedback_context_sources_for_category("user_fit", top_docs=examples)
    legacy = legacy_context_string_default_source_for_category("user_fit", top_docs=examples)
    return _call_vendor_feedback_items(
        client,
        ModelSize.TINY,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
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

@traceable(run_type="chain", name="human_check")
def human_check(letter: str, examples: Sequence[TopDocument], client: BaseClient) -> List[Dict[str, Any]]:
    """Check the letter for consistency with the instructions."""
    prompts = build_phased_feedback_checker_prompts("human", letter=letter, top_docs=examples)
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
        ModelSize.TINY,
        system,
        prompt,
        allowed_context_sources=allowed,
        legacy_string_source=legacy,
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
) -> str:
    """Build the topic-specific context string for agentic feedback prompts.
    Returns the context blocks (excluding the draft letter itself) to include in the prompt.
    If draft_letters is provided (vendor -> text), multiple proposals are shown so agents can compare and prefer one vendor's choice.
    """
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
            context_items: List[str] = []
            cf = it.get("context_field")
            if isinstance(cf, dict) and isinstance(cf.get("items"), list):
                for raw in (cf.get("items", []) or []):
                    if isinstance(raw, str):
                        t = raw.strip()
                        if t:
                            context_items.append(t)
                        continue
                    if isinstance(raw, dict):
                        t = str(raw.get("text") or "").strip()
                        src = str(raw.get("source") or "").strip().upper()
                        if not t:
                            continue
                        if src in FEEDBACK_CONTEXT_SOURCES_FROZEN:
                            context_items.append(f"[{src}] {t}")
                        else:
                            context_items.append(t)
            user_context = (it.get("user_context") or "").strip() if isinstance(it.get("user_context") or "", str) else ""
            input_declined = bool(it.get("input_declined")) if status == "INPUT_NEEDED" else False

            # Keep the base observation first (this is the actionable critique).
            extra: List[str] = []
            if context_items:
                extra.append("Available context: " + "; ".join(context_items))
            if status == "INPUT_NEEDED" and user_context:
                extra.append("User-provided context: " + user_context)
            if status == "INPUT_NEEDED" and input_declined and not user_context:
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
    user_fit_feedback: Any,
    human_feedback: Any,
    client: BaseClient,
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
    dim_blocks = (
        ("Instruction Feedback", instruction_feedback),
        ("Accuracy Feedback", accuracy_feedback),
        ("Precision Feedback", precision_feedback),
        ("Company Fit Feedback", company_fit_feedback),
        ("User Fit Feedback", user_fit_feedback),
        ("Human Feedback", human_feedback),
    )
    for title, val in dim_blocks:
        block = _rewrite_dimension_text(val)
        if not block:
            continue
        had_feedback = True
        prompt += f"========== {title}:\n" + block + "\n==========\n"
    if not had_feedback:
        logger.info("No feedback provided, returning original letter.")
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
        logger.info("No revisions needed, returning original letter.")
        return original_letter
    return revised_letter 

@traceable(run_type="chain", name="fancy_letter")
def fancy_letter(letter: str, client: BaseClient) -> str:
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

