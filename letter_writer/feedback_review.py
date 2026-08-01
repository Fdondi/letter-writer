"""
Post-process structured draft feedback: filter noise, justify critiques, dedupe within vendor,
and align INPUT_NEEDED rows across vendors. Costs are tracked as phase \"feedback_review\".
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .generation import normalize_feedback_map, format_known_weaknesses_block, KNOWN_WEAKNESSES_FEEDBACK_RULES
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

FEEDBACK_REVIEW_PHASE = "feedback_review"

FEEDBACK_CATEGORY_KEYS = (
    "instruction",
    "accuracy",
    "precision",
    "company_fit",
    "goal_fit",
    "user_fit",
    "human",
)


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        lines = text.split("\n")
        inner = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
        text = inner.strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def _flatten_feedback(feedback: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    for cat in FEEDBACK_CATEGORY_KEYS:
        for it in feedback.get(cat) or []:
            if isinstance(it, dict) and it.get("id"):
                out.append((cat, it))
    return out


def _rebuild_feedback(
    flat: List[Tuple[str, Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {k: [] for k in FEEDBACK_CATEGORY_KEYS}
    for cat, it in flat:
        buckets.setdefault(cat, []).append(it)
    return buckets


def _build_justification_context(
    category: str,
    *,
    draft_letter: str,
    style_instructions: str,
    cv_text: str,
    additional_user_info: str,
    company_report: str,
    job_text: str,
    top_docs: Sequence[TopDocument],
    hire_problem: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """Mirror the checker inputs so the reviewer can judge whether the critique is fair."""
    from .generation import get_style_instructions

    si = style_instructions or get_style_instructions()
    letter = draft_letter or ""
    cv = cv_text or ""
    cr = company_report or ""
    jt = job_text or ""
    add = (additional_user_info or "").strip()
    kw_suffix = format_known_weaknesses_block(known_weaknesses)

    if category == "instruction":
        return (
            "========== Style Instructions:\n"
            + si
            + "\n==========\n\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
            + kw_suffix
        )
    if category == "accuracy":
        extra = ""
        if add:
            extra = (
                "\n\nUser additional info (may explain facts not in CV):\n" + add + "\n"
            )
        return (
            "========== User CV:\n"
            + cv
            + "\n==========\n\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
            + extra
            + kw_suffix
        )
    if category in ("precision", "company_fit"):
        return (
            "========== Company Report:\n"
            + cr
            + "\n==========\n\n========== Job Offer:\n"
            + jt
            + "\n==========\n\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
            + kw_suffix
        )
    if category == "goal_fit":
        hp = (hire_problem or "").strip()
        prefix = ""
        if hp:
            prefix = (
                "========== Hire goal / problem this role solves (structured extraction):\n"
                + hp
                + "\n==========\n\n"
            )
        return (
            prefix
            + "========== Company Report:\n"
            + cr
            + "\n==========\n\n========== Job Offer:\n"
            + jt
            + "\n==========\n\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
            + kw_suffix
        )
    if category == "user_fit":
        examples_formatted = "\n\n".join(
            f"---- Example #{i+1} - {ex.get('company_name', '')} ----\n"
            f"Cover Letter:\n{ex.get('letter_text', '')}\n\n"
            for i, ex in enumerate(top_docs)
            if ex.get("letter_text")
        )
        if not examples_formatted.strip():
            examples_formatted = "(No reference letters available.)"
        cv_block = cv.strip()
        if not cv_block:
            cv_block = "(No CV text was provided in this session.)"
        extra = ""
        if add:
            extra = (
                "\n\n========== User's additional info (relevant but not fully captured in CV):\n"
                + add
                + "\n==========\n"
            )
        return (
            "========== Reference Examples:\n"
            + examples_formatted
            + "\n==========\n\n========== User CV:\n"
            + cv_block
            + "\n==========\n"
            + extra
            + "\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
            + kw_suffix
        )
    if category == "human":
        examples_formatted = "\n\n".join(
            f"---- Example #{i+1} - {ex.get('company_name', '')} ----\n"
            f"Cover Letter:\n{ex.get('letter_text', '')}\n\n"
            for i, ex in enumerate(top_docs)
            if ex.get("letter_text")
        )
        return (
            "========== Reference Examples:\n"
            + examples_formatted
            + "\n==========\n\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
            + kw_suffix
        )
    return "========== Cover Letter:\n" + letter + "\n==========\n" + kw_suffix


@traceable(run_type="chain", name="feedback_review_stage12_batch")
def _stage12_batch(
    client: BaseClient,
    category: str,
    items: List[Tuple[str, str]],
    context_block: str,
) -> Dict[str, bool]:
    """Combined stages 1+2 in a single call: filter incoherent AND unjustified items.

    Sending all observations for a category at once (instead of one call per item)
    is the primary cost reduction: the large context block is paid once per category
    rather than once per observation.  ``system_cache_prefix`` places that context in a
    cached system block so retries get a read hit; precision and company_fit also share
    the same prefix (company_report + job_text + letter) and get a cross-call cache hit.

    Returns ``{id: keep_bool}`` for every provided item; unknown ids default to True
    (fail-open so a partial JSON parse never silently drops valid observations).
    """
    if not items:
        return {}
    system_cache_prefix = (
        f"========== Context the checker saw ==========\n{context_block}"
    )
    system = (
        f"Category: {category}\n\n"
        "You filter cover-letter critique bullets in bulk.\n"
        "For each item set keep=false if it is:\n"
        "  • incoherent, empty, tautological, or not actionable, OR\n"
        "  • unjustified: misreads the letter, claims a mismatch not supported by the context, "
        "or demands something already present, OR\n"
        "  • asks to fix an objective known weakness (missing cert, language level, etc.) when the letter already "
        "honestly acknowledges and frames the gap with truthful wording — see known weaknesses block in context if present.\n"
        "  • Do NOT set keep=false for critiques that catch dishonest framing of a known weakness (inflated labels, "
        "false fluency, incompatible level claims).\n"
        + KNOWN_WEAKNESSES_FEEDBACK_RULES
        + "\nOtherwise keep=true.\n"
        "Reply JSON only: {\"results\": [{\"id\": \"<id>\", \"keep\": true}, ...]}\n"
        "Return exactly one object per id — no omissions."
    )
    lines = [f"id={oid}: {obs.strip()[:1200]}" for oid, obs in items]
    prompt = "Critiques:\n" + "\n".join(lines)
    from .clients.prompt_cache import cache_key_for_prefix

    cache_key = cache_key_for_prefix(system_cache_prefix, fallback=f"feedback_review:{category}")
    raw = client.call(
        ModelRole.FEEDBACK_REVIEW,
        system,
        [prompt],
        system_cache_prefix=system_cache_prefix,
        prompt_cache_key=cache_key,
    )
    def _parse_results(raw_response: str) -> Dict[str, bool]:
        data = _extract_json_object(raw_response)
        parsed: Dict[str, bool] = {}
        for r in (data.get("results") or []):
            if isinstance(r, dict):
                parsed[str(r.get("id", ""))] = bool(r.get("keep", True))
        return parsed

    out = _parse_results(raw)

    # Retry once for any ids the model omitted
    all_ids = {oid for oid, _ in items}
    missing_ids = all_ids - out.keys()
    if missing_ids:
        missing_items = [(oid, obs) for oid, obs in items if oid in missing_ids]
        logger.debug(
            "stage12_batch category=%s: %d/%d ids missing, retrying",
            category, len(missing_ids), len(items),
        )
        retry_lines = [f"id={oid}: {obs.strip()[:1200]}" for oid, obs in missing_items]
        retry_prompt = "Critiques:\n" + "\n".join(retry_lines)
        retry_raw = client.call(
            ModelRole.FEEDBACK_REVIEW,
            system,
            [retry_prompt],
            system_cache_prefix=system_cache_prefix,
            prompt_cache_key=cache_key,
        )
        out.update(_parse_results(retry_raw))

    return out


def _input_cluster_duplicate_group_id(cluster_key: str) -> str:
    """Stable duplicate_group_id for INPUT_NEEDED rows sharing input_cluster_key."""
    slug = str(cluster_key or "").strip()
    return "inp_" + hashlib.sha256(slug.encode("utf-8")).hexdigest()[:12]


def apply_input_cluster_duplicate_groups(feedback: Dict[str, Any]) -> None:
    """
    INPUT_NEEDED items with the same input_cluster_key share duplicate_group_id.
    Mutates feedback in place.
    """
    for cat in FEEDBACK_CATEGORY_KEYS:
        for it in feedback.get(cat) or []:
            if not isinstance(it, dict):
                continue
            if str(it.get("status", "")).upper() != "INPUT_NEEDED":
                continue
            ck = str(it.get("input_cluster_key") or "").strip()
            if ck:
                it["duplicate_group_id"] = _input_cluster_duplicate_group_id(ck)
            else:
                dg = str(it.get("duplicate_group_id") or "")
                if dg.startswith("inp_"):
                    del it["duplicate_group_id"]


@traceable(run_type="chain", name="feedback_review_stage3_duplicate_groups")
def _stage3_duplicate_groups(
    client: BaseClient,
    items: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Assign duplicate_group_id for non-INPUT_NEEDED observations that are the same issue across categories.
    INPUT_NEEDED linking is handled only via input_cluster_key (phase 4), not this call.
    Items must include 'id' and 'category' and 'observation'.
    """
    if len(items) < 2:
        return {}
    system = (
        "You group cover-letter feedback observations that are essentially the SAME issue "
        "(same underlying problem), possibly worded differently across categories.\n"
        "The list excludes INPUT_NEEDED rows (those are grouped separately by what information is missing).\n"
        "Do not group items that are really about different problems.\n"
        "Reply JSON only: {\"groups\": [[\"id1\",\"id2\"], [\"id3\"]]} "
        "Each inner array lists item ids that should be linked. Observations that are unique form single-id groups "
        "or may be omitted. Use only the ids provided. Empty groups array if nothing duplicates."
    )
    lines = []
    for it in items:
        lines.append(
            f"- id={it['id']} category={it.get('category')} :: {it.get('observation', '')[:1200]}"
        )
    prompt = "Items:\n" + "\n".join(lines)
    raw = client.call(ModelRole.FEEDBACK_REVIEW, system, [prompt])
    data = _extract_json_object(raw)
    groups = data.get("groups")
    id_to_group: Dict[str, str] = {}
    if not isinstance(groups, list):
        return {}
    for g in groups:
        if not isinstance(g, list) or len(g) < 2:
            continue
        ids = [str(x).strip() for x in g if str(x).strip()]
        if len(ids) < 2:
            continue
        gid = str(uuid.uuid4())[:12]
        for i in ids:
            id_to_group[i] = gid
    return id_to_group


@traceable(run_type="chain", name="feedback_review_stage4_input_clusters")
def _stage4_input_clusters(
    client: BaseClient,
    rows: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Map item id -> input_cluster_key for INPUT_NEEDED rows (semantic equivalence across vendors/categories).
    rows: {id, vendor, category, observation, user_instructions}
    """
    if not rows:
        return {}
    composite = any("::" in str(r.get("id", "")) for r in rows)
    id_hint = (
        "Each id may be a composite string vendor::category::item_id — copy ids EXACTLY from the list."
        if composite
        else "Use the exact id strings from the list."
    )
    system = (
        "Several models asked the user for missing information. Cluster rows that ask for the SAME kind of information "
        "(same facts needed to answer).\n"
        "Rows that ask for DIFFERENT information must get DIFFERENT cluster keys — do not put them in the same cluster.\n"
        "Reply JSON only: {\"clusters\": [{\"key\": \"short_slug_like_languages\", \"ids\": [\"...\",\"...\"]}]}.\n"
        "Use stable, short snake_case keys (a-z0-9_). Same key means the UI can pre-fill one answer everywhere.\n"
        + id_hint
    )
    lines = []
    for r in rows:
        lines.append(
            f"- id={r['id']} vendor={r.get('vendor')} category={r.get('category')} :: "
            f"obs={str(r.get('observation',''))[:400]} :: hint={str(r.get('user_instructions',''))[:200]}"
        )
    prompt = "Rows:\n" + "\n".join(lines)
    raw = client.call(ModelRole.FEEDBACK_REVIEW, system, [prompt])
    data = _extract_json_object(raw)
    clusters = data.get("clusters")
    out: Dict[str, str] = {}
    if not isinstance(clusters, list):
        return {}
    for c in clusters:
        if not isinstance(c, dict):
            continue
        key = str(c.get("key") or "").strip()
        ids = c.get("ids")
        if not key or not isinstance(ids, list):
            continue
        slug = re.sub(r"[^a-z0-9_]+", "_", key.lower()).strip("_")[:64] or "cluster"
        for i in ids:
            sid = str(i).strip()
            if sid:
                out[sid] = slug
    return out


def _parallel_stage12(
    client: BaseClient,
    cat_to_items: Dict[str, List[Tuple[str, str]]],
    ctx_cache: Dict[str, str],
) -> Dict[str, bool]:
    """Run _stage12_batch per category, grouped by shared context cache key.

    Categories that share the same ``context_block`` run sequentially so the
    provider reuses one cache write; independent context groups run in parallel.
    """
    if not cat_to_items:
        return {}
    from .clients.prompt_cache import cache_key_for_prefix, run_cache_grouped_tasks

    out: Dict[str, bool] = {}

    def _run_cat(cat: str) -> Dict[str, bool]:
        return _stage12_batch(client, cat, cat_to_items[cat], ctx_cache[cat])

    tasks: List[Tuple[str, Optional[str], Any]] = []
    for cat in cat_to_items:
        ctx = ctx_cache.get(cat, "")
        tasks.append((cat, ctx, lambda c=cat: _run_cat(c)))

    grouped_results = run_cache_grouped_tasks(tasks, max_parallel_groups=7)
    for cat, keep_map in grouped_results.items():
        if isinstance(keep_map, dict):
            out.update(keep_map)
    return out


def review_feedback_for_vendor(
    *,
    client: BaseClient,
    draft_letter: str,
    feedback: Dict[str, Any],
    style_instructions: str,
    cv_text: str,
    additional_user_info: str,
    company_report: str,
    job_text: str,
    top_docs: Sequence[TopDocument],
    vendor: str,
    hire_problem: str = "",
    known_weaknesses: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Stages 1+2 combined (one batch call per category, run in parallel), then
    stages 3 and 4 sequentially.  Mutates no inputs; returns new feedback dict.
    """
    fb = normalize_feedback_map(feedback, top_docs=top_docs)
    flat = _flatten_feedback(fb)
    if not flat:
        return fb

    # --- Stages 1+2 combined: one batched call per category (parallel) ---
    # Build context cache and group items by category in a single pass.
    ctx_cache: Dict[str, str] = {}
    cat_to_items: Dict[str, List[Tuple[str, str]]] = {}
    for cat, it in flat:
        obs = str(it.get("observation", "")).strip()
        if not obs:
            continue
        if cat not in ctx_cache:
            ctx_cache[cat] = _build_justification_context(
                cat,
                draft_letter=draft_letter,
                style_instructions=style_instructions,
                cv_text=cv_text,
                additional_user_info=additional_user_info,
                company_report=company_report,
                job_text=job_text,
                top_docs=top_docs,
                hire_problem=hire_problem,
                known_weaknesses=known_weaknesses,
            )
        cat_to_items.setdefault(cat, []).append((str(it["id"]), obs))

    keep_map = _parallel_stage12(client, cat_to_items, ctx_cache) if cat_to_items else {}
    flat_s2: List[Tuple[str, Dict[str, Any]]] = [
        (cat, it)
        for cat, it in flat
        if str(it.get("observation", "")).strip() and keep_map.get(str(it["id"]), True)
    ]

    rebuilt = _rebuild_feedback(flat_s2)

    # --- Stage 4 (before stage 3): INPUT_NEEDED cluster keys — same info → same key ---
    rows: List[Dict[str, Any]] = []
    for cat in FEEDBACK_CATEGORY_KEYS:
        for it in rebuilt.get(cat) or []:
            if str(it.get("status", "")).upper() != "INPUT_NEEDED":
                continue
            rows.append(
                {
                    "id": str(it["id"]),
                    "vendor": vendor,
                    "category": cat,
                    "observation": str(it.get("observation", "")),
                    "user_instructions": str(it.get("user_instructions", "")),
                }
            )
    id_to_cluster = _stage4_input_clusters(client, rows) if rows else {}
    for cat in FEEDBACK_CATEGORY_KEYS:
        for it in rebuilt.get(cat) or []:
            if str(it.get("status", "")).upper() != "INPUT_NEEDED":
                if "input_cluster_key" in it:
                    del it["input_cluster_key"]
                continue
            iid = str(it.get("id", ""))
            ck = id_to_cluster.get(iid)
            if ck:
                it["input_cluster_key"] = ck
            elif "input_cluster_key" in it:
                del it["input_cluster_key"]

    # --- Stage 3: duplicate groups for non-INPUT_NEEDED only (LLM) ---
    stage3_items: List[Dict[str, Any]] = []
    for cat in FEEDBACK_CATEGORY_KEYS:
        for it in rebuilt.get(cat) or []:
            if not isinstance(it, dict):
                continue
            if str(it.get("status", "")).upper() == "INPUT_NEEDED":
                continue
            stage3_items.append(
                {
                    "id": str(it["id"]),
                    "category": cat,
                    "observation": str(it.get("observation", "")),
                }
            )
    dup_map = _stage3_duplicate_groups(client, stage3_items) if len(stage3_items) >= 2 else {}
    for cat in FEEDBACK_CATEGORY_KEYS:
        for it in rebuilt.get(cat) or []:
            if not isinstance(it, dict):
                continue
            if str(it.get("status", "")).upper() == "INPUT_NEEDED":
                continue
            iid = str(it.get("id", ""))
            gid = dup_map.get(iid)
            if gid:
                it["duplicate_group_id"] = gid
            elif "duplicate_group_id" in it:
                del it["duplicate_group_id"]

    apply_input_cluster_duplicate_groups(rebuilt)

    return rebuilt


def merge_input_clusters_across_session_vendors(
    *,
    session: Any,
    client: BaseClient,
) -> None:
    """
    After per-vendor review, assign consistent input_cluster_key for INPUT_NEEDED across all vendors'
    feedback in the session. Mutates session.vendors in place.
    """
    rows: List[Dict[str, Any]] = []
    for v_name, v_state in (session.vendors or {}).items():
        fb = normalize_feedback_map(
            getattr(v_state, "feedback", None),
            top_docs=getattr(v_state, "top_docs", None),
        )
        for cat in FEEDBACK_CATEGORY_KEYS:
            for it in fb.get(cat) or []:
                if str(it.get("status", "")).upper() != "INPUT_NEEDED":
                    continue
                rows.append(
                    {
                        "id": f"{v_name}::{cat}::{it.get('id')}",
                        "vendor": v_name,
                        "category": cat,
                        "observation": str(it.get("observation", "")),
                        "user_instructions": str(it.get("user_instructions", "")),
                    }
                )
    if len(rows) < 2:
        return
    mapping = _stage4_input_clusters(client, rows)
    # Apply: map back to nested ids
    for v_name, v_state in (session.vendors or {}).items():
        fb = getattr(v_state, "feedback", None) or {}
        changed = False
        for cat in FEEDBACK_CATEGORY_KEYS:
            lst = fb.get(cat)
            if not isinstance(lst, list):
                continue
            for it in lst:
                if not isinstance(it, dict):
                    continue
                if str(it.get("status", "")).upper() != "INPUT_NEEDED":
                    continue
                composite = f"{v_name}::{cat}::{it.get('id')}"
                ck = mapping.get(composite)
                if ck:
                    if it.get("input_cluster_key") != ck:
                        it["input_cluster_key"] = ck
                        changed = True
        if changed:
            v_state.feedback = fb

    for _v_name, v_state in (session.vendors or {}).items():
        fb = getattr(v_state, "feedback", None) or {}
        if isinstance(fb, dict):
            apply_input_cluster_duplicate_groups(fb)
