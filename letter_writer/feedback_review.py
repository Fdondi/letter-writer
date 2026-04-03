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
from typing import Any, Dict, List, Sequence, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelSize
from .generation import normalize_feedback_map
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

FEEDBACK_REVIEW_PHASE = "feedback_review"

FEEDBACK_CATEGORY_KEYS = (
    "instruction",
    "accuracy",
    "precision",
    "company_fit",
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
) -> str:
    """Mirror the checker inputs so the reviewer can judge whether the critique is fair."""
    from .generation import get_style_instructions

    si = style_instructions or get_style_instructions()
    letter = draft_letter or ""
    cv = cv_text or ""
    cr = company_report or ""
    jt = job_text or ""
    add = (additional_user_info or "").strip()

    if category == "instruction":
        return (
            "========== Style Instructions:\n"
            + si
            + "\n==========\n\n========== Cover Letter:\n"
            + letter
            + "\n==========\n"
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
        )
    if category in ("user_fit", "human"):
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
        )
    return "========== Cover Letter:\n" + letter + "\n==========\n"


@traceable(run_type="chain", name="feedback_review_stage1_meaningful")
def _stage1_meaningful(client: BaseClient, observation: str) -> bool:
    """No surrounding letter context: drop incoherent / empty noise."""
    system = (
        "You filter critique bullets about cover letters. You only see ONE observation in isolation.\n"
        "Decide if it expresses a coherent, substantive claim (something a reviewer could act on).\n"
        "Reply with JSON only: {\"keep\": true} or {\"keep\": false}.\n"
        "Use keep=false for: empty noise; tautologies; 'corrections' that change nothing; self-contradiction; "
        "nonsense dates or logic stated as fact (e.g. impossible timelines); text that does not say anything actionable."
    )
    prompt = "Observation:\n" + (observation or "").strip() + "\n\nJSON only."
    raw = client.call(ModelSize.TINY, system, [prompt])
    data = _extract_json_object(raw)
    return bool(data.get("keep"))


@traceable(run_type="chain", name="feedback_review_stage2_justified")
def _stage2_justified(
    client: BaseClient,
    category: str,
    observation: str,
    context_block: str,
) -> bool:
    """Same materials the checker had plus the letter: is the critique fair?"""
    system = (
        "You judge whether ONE critique of a cover letter is fair given the SAME background text the checker had.\n"
        "Reply JSON only: {\"justified\": true} or {\"justified\": false}.\n"
        "justified=false if the critique misreads the letter (e.g. attacks wording that is reasonable in context), "
        "or claims a mismatch that the letter/context does not support, or demands something already satisfied."
    )
    prompt = (
        f"Category: {category}\n\n"
        f"========== Context the checker saw ==========\n{context_block}\n\n"
        f"========== Critique to judge ==========\n{observation.strip()}\n"
    )
    raw = client.call(ModelSize.TINY, system, [prompt])
    data = _extract_json_object(raw)
    return bool(data.get("justified"))


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
    raw = client.call(ModelSize.TINY, system, [prompt])
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
    raw = client.call(ModelSize.TINY, system, [prompt])
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


def _parallel_stage1(
    client: BaseClient,
    id_to_observation: Dict[str, str],
) -> Dict[str, bool]:
    """Parallel meaningful checks; same client as phased_service parallel checks."""
    if not id_to_observation:
        return {}
    out: Dict[str, bool] = {}
    max_workers = min(16, len(id_to_observation))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(_stage1_meaningful, client, obs): oid
            for oid, obs in id_to_observation.items()
        }
        for fut in as_completed(futs):
            oid = futs[fut]
            try:
                out[oid] = fut.result()
            except Exception as e:
                logger.warning("feedback review stage1 failed id=%s: %s", oid, e)
                out[oid] = True
    return out


def _parallel_stage2(
    client: BaseClient,
    id_to_triple: Dict[str, Tuple[str, str, str]],
) -> Dict[str, bool]:
    """id -> (category, observation, context_block)."""
    if not id_to_triple:
        return {}
    out: Dict[str, bool] = {}
    max_workers = min(16, len(id_to_triple))

    def _run_one(oid: str, triple: Tuple[str, str, str]) -> Tuple[str, bool]:
        cat, obs, ctx = triple
        return oid, _stage2_justified(client, cat, obs, ctx)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_run_one, oid, tpl): oid for oid, tpl in id_to_triple.items()}
        for fut in as_completed(futs):
            oid = futs[fut]
            try:
                o, ok = fut.result()
                out[o] = ok
            except Exception as e:
                logger.warning("feedback review stage2 failed id=%s: %s", oid, e)
                out[oid] = True
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
) -> Dict[str, Any]:
    """
    Sequential stages; parallelize independent LLM calls within stages 1 and 2.
    Mutates no inputs; returns new feedback dict.
    """
    fb = normalize_feedback_map(feedback)
    flat = _flatten_feedback(fb)
    if not flat:
        return fb

    # --- Stage 1 (parallel per observation) ---
    id_to_obs: Dict[str, str] = {}
    for _cat, it in flat:
        oid = str(it["id"])
        obs = str(it.get("observation", "")).strip()
        if obs:
            id_to_obs[oid] = obs
    s1 = _parallel_stage1(client, id_to_obs) if id_to_obs else {}
    flat_s1: List[Tuple[str, Dict[str, Any]]] = []
    for cat, it in flat:
        oid = str(it["id"])
        obs = str(it.get("observation", "")).strip()
        if not obs:
            continue
        if id_to_obs and not s1.get(oid, True):
            continue
        flat_s1.append((cat, it))

    # --- Stage 2 (parallel; depends on stage 1 survivors) ---
    ctx_cache: Dict[str, str] = {}
    id_to_triple: Dict[str, Tuple[str, str, str]] = {}
    for cat, it in flat_s1:
        oid = str(it["id"])
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
            )
        obs = str(it.get("observation", "")).strip()
        ctx = ctx_cache[cat]
        id_to_triple[oid] = (cat, obs, ctx)
    s2 = _parallel_stage2(client, id_to_triple) if id_to_triple else {}
    flat_s2: List[Tuple[str, Dict[str, Any]]] = []
    for cat, it in flat_s1:
        oid = str(it["id"])
        if id_to_triple and not s2.get(oid, True):
            continue
        flat_s2.append((cat, it))

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
        fb = normalize_feedback_map(getattr(v_state, "feedback", None))
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
