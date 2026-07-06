"""Inline letter autocomplete: LLM calls, memoization, and persistence hooks."""

from __future__ import annotations

import hashlib
import logging
import time
from threading import Lock
from typing import Any, Dict, List, Optional

from letter_writer.autocomplete_core import (
    autocomplete_cache_fetch_max_words,
    build_all_sections_plan_user_prompt,
    context_summary_max_chars,
    build_autocomplete_cache_prefix,
    build_context_summary_user_prompt,
    build_section_plan_user_prompt,
    finalize_plan_context_summary,
    normalize_autocomplete_model_key,
    parse_autocomplete_plan_batch_json,
    parse_autocomplete_section_plan_response,
    parse_autocomplete_vendor,
    resolve_autocomplete_plan_model,
    finalize_autocomplete_suggestion,
    should_extend_autocomplete_cache,
    slice_next_autocomplete_chunk,
)
from letter_writer.client import get_client
from letter_writer.clients.base import ModelRole
from letter_writer.cost_tracker import track_api_cost
from letter_writer.language_settings import build_language_system_prefix
from letter_writer.generation import get_style_instructions
from letter_writer.personal_data_sections import (
    get_autocomplete_max_words,
    get_autocomplete_stop_on_period,
    get_style_instructions as get_user_style_instructions,
)
from letter_writer.phased_service import _reset_client_counters

logger = logging.getLogger(__name__)

_MEMO_LOCK = Lock()
_MEMO: Dict[str, tuple] = {}
_MEMO_TTL_SEC = 90.0


def _memo_key(
    user_id: str,
    model_key: str,
    prefix: str,
    max_words: int,
    stop_on_period: bool,
    cache_prefix: str,
) -> str:
    h = hashlib.sha256()
    h.update(user_id.encode("utf-8"))
    h.update(model_key.encode("utf-8"))
    h.update(prefix.encode("utf-8"))
    h.update(str(max_words).encode())
    h.update(str(stop_on_period).encode())
    h.update(cache_prefix.encode("utf-8"))
    return h.hexdigest()


def _memo_get(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _MEMO_LOCK:
        entry = _MEMO.get(key)
        if not entry:
            return None
        ts, payload = entry
        if now - ts > _MEMO_TTL_SEC:
            _MEMO.pop(key, None)
            return None
        return dict(payload)


def _memo_set(key: str, payload: Dict[str, Any]) -> None:
    with _MEMO_LOCK:
        if len(_MEMO) > 500:
            _MEMO.clear()
        _MEMO[key] = (time.time(), dict(payload))


def run_autocomplete_completion(
    *,
    user_id: str,
    user_data: Dict[str, Any],
    prefix: str,
    model_key: str,
    cv_text: str,
    job_text: str,
    style_instructions: str,
    additional_user_info: str = "",
    additional_company_info: str = "",
    structure_instructions: str = "",
    company_report: str = "",
    top_docs: Optional[List[Dict[str, Any]]] = None,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
    max_words: Optional[int] = None,
    stop_on_period: Optional[bool] = None,
    allow_memo: bool = True,
    plan_context_summary: str = "",
    active_section_plan: str = "",
    active_section_proposal: str = "",
    section_proposal_stale: bool = False,
    text_before_cursor: str = "",
    cache_offset: int = 0,
    extend_cache: bool = False,
) -> Dict[str, Any]:
    """Call LLM to continue ``prefix`` with a short inline suggestion."""
    max_w = max_words if max_words is not None else get_autocomplete_max_words(user_data)
    stop_period = (
        stop_on_period
        if stop_on_period is not None
        else get_autocomplete_stop_on_period(user_data)
    )
    max_w = max(1, min(100, int(max_w)))
    fetch_max_w = autocomplete_cache_fetch_max_words(max_w)
    cache_offset = max(0, int(cache_offset or 0))

    style = (style_instructions or "").strip()
    if not style:
        style = get_user_style_instructions(user_data) or get_style_instructions()

    cache_prefix = build_autocomplete_cache_prefix(
        cv_text=cv_text or "",
        job_text=job_text or "",
        style_instructions=style,
        structure_instructions=structure_instructions or "",
        additional_user_info=additional_user_info or "",
        additional_company_info=additional_company_info or "",
        company_report=company_report or "",
        top_docs=top_docs,
        company_name=company_name or "",
        job_title=job_title or "",
        location=location or "",
        language=language or "",
        salary=salary or "",
        requirements=requirements,
        competences=competences,
        point_of_contact=point_of_contact,
        plan_context_summary=plan_context_summary or "",
        active_section_plan=active_section_plan or "",
        active_section_proposal=active_section_proposal or "",
        section_proposal_stale=section_proposal_stale,
        language_prefix=build_language_system_prefix(user_data or {}, language or ""),
    )

    normalized_key = normalize_autocomplete_model_key(model_key) or model_key

    memo_key = _memo_key(
        user_id, normalized_key, prefix, max_w, stop_period, cache_prefix
    )

    def _result_from_cached_raw(
        raw_cached: str,
        *,
        offset: int,
        cache_hit: bool,
        base: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        chunk, new_offset, truncated_by, has_more = slice_next_autocomplete_chunk(
            raw_cached,
            offset,
            max_words=max_w,
            stop_on_period=stop_period,
        )
        suggestion, _, warnings = finalize_autocomplete_suggestion(
            chunk,
            max_words=max_w,
            stop_on_period=stop_period,
            text_before_cursor=text_before_cursor,
        )
        if not suggestion and warnings:
            return None
        out: Dict[str, Any] = dict(base) if base else {}
        out.update(
            {
                "suggestion_text": suggestion,
                "truncated_by": truncated_by,
                "cache_hit": cache_hit,
                "cache_prefix": cache_prefix,
                "raw_suggestion_text": raw_cached,
                "cache_offset": offset,
                "cache_offset_next": new_offset,
                "cache_has_more": has_more,
                "extend_cache_recommended": should_extend_autocomplete_cache(
                    new_offset, len(raw_cached)
                ),
                "max_words": max_w,
                "stop_on_period": stop_period,
            }
        )
        if warnings:
            out["warnings"] = warnings
        else:
            out.pop("warnings", None)
        return out

    if allow_memo and cache_offset > 0 and not extend_cache:
        cached = _memo_get(memo_key)
        if cached is not None:
            raw_cached = (
                cached.get("raw_suggestion_text") or cached.get("suggestion_text") or ""
            ).strip()
            if raw_cached and cache_offset < len(raw_cached):
                sliced = _result_from_cached_raw(
                    raw_cached, offset=cache_offset, cache_hit=True, base=cached
                )
                if sliced is not None:
                    return sliced

    if allow_memo and not extend_cache and cache_offset == 0:
        cached = _memo_get(memo_key)
        if cached is not None:
            raw_cached = (
                cached.get("raw_suggestion_text") or cached.get("suggestion_text") or ""
            ).strip()
            if raw_cached:
                sliced = _result_from_cached_raw(
                    raw_cached, offset=0, cache_hit=True, base=cached
                )
                if sliced is not None and sliced.get("suggestion_text"):
                    return sliced
            # Stale or empty memo entry — fall through to a fresh LLM call.

    vendor = parse_autocomplete_vendor(normalized_key)
    client = get_client(vendor)
    _reset_client_counters(client)

    model_override = normalized_key.split("/", 1)[1] if "/" in normalized_key else None
    model_role: ModelRole | str = model_override if model_override else ModelRole.AUTOCOMPLETE

    existing_raw = ""
    if extend_cache and allow_memo:
        cached = _memo_get(memo_key)
        if cached:
            existing_raw = (
                cached.get("raw_suggestion_text") or cached.get("suggestion_text") or ""
            ).strip()

    if prefix.strip():
        if extend_cache and existing_raw:
            limit_instruction = (
                f"Continue the cover letter text with at most {fetch_max_w} more words. "
                "Do not stop at the first period — write through multiple sentences. "
                "Output only the new continuation text — no quotes, labels, or commentary. "
                "Do not repeat text already written. "
                "Do not output section headings or descriptions — only the next part of the letter body."
            )
            user_prompt = (
                f"{prefix}\n\n"
                f"[Already suggested continuation (do not repeat):]\n{existing_raw}\n\n"
                f"{limit_instruction}"
            )
        else:
            limit_instruction = (
                f"Continue the cover letter text with at most {fetch_max_w} words. "
                "Do not stop at the first period — write through multiple sentences. "
                "Output only the continuation text — no quotes, labels, or commentary. "
                "Do not repeat text already written. "
                "Do not output section headings or descriptions — only the next part of the letter body."
            )
            user_prompt = f"{prefix}\n\n{limit_instruction}"
    else:
        limit_instruction = (
            f"Write the opening of the cover letter with at most {fetch_max_w} words. "
            "Do not stop at the first period — write through multiple sentences. "
            "Output only the new letter text — no quotes, labels, or commentary."
        )
        user_prompt = limit_instruction
    if prefix.strip():
        system = (
            "You are an expert cover letter writing assistant. "
            "Continue the user's draft naturally in the same language and tone."
        )
    else:
        system = (
            "You are an expert cover letter writing assistant. "
            "Write a strong opening using the job and candidate context provided."
        )

    raw = client.call(
        model_role,
        system,
        [user_prompt],
        system_cache_prefix=cache_prefix or None,
    )

    new_raw = (raw or "").strip()
    if extend_cache and existing_raw:
        raw_suggestion = (existing_raw + new_raw).strip()
    else:
        raw_suggestion = new_raw

    chunk, cache_offset_next, truncated_by, cache_has_more = slice_next_autocomplete_chunk(
        raw_suggestion,
        cache_offset,
        max_words=max_w,
        stop_on_period=stop_period,
    )
    suggestion, _, warnings = finalize_autocomplete_suggestion(
        chunk,
        max_words=max_w,
        stop_on_period=stop_period,
        text_before_cursor=text_before_cursor,
    )

    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    cached_tokens = int(getattr(client, "total_cached_tokens", 0) or 0)

    if cost > 0:
        track_api_cost(
            user_id,
            "autocomplete",
            vendor.value,
            cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens if cached_tokens else None,
        )

    result: Dict[str, Any] = {
        "suggestion_text": suggestion,
        "model_used": normalized_key,
        "cost": cost,
        "cached_tokens": cached_tokens,
        "truncated_by": truncated_by,
        "cache_hit": False,
        "max_words": max_w,
        "stop_on_period": stop_period,
        "cache_prefix": cache_prefix,
        "cache_offset": cache_offset,
        "cache_offset_next": cache_offset_next,
        "cache_has_more": cache_has_more,
        "extend_cache_recommended": should_extend_autocomplete_cache(
            cache_offset_next, len(raw_suggestion)
        ),
    }
    if warnings:
        result["warnings"] = warnings
    if raw_suggestion:
        result["raw_suggestion_text"] = raw_suggestion

    if allow_memo and raw_suggestion:
        _memo_set(memo_key, result)

    return result


def _autocomplete_plan_client_setup(
    *,
    user_data: Dict[str, Any],
    model_key: Optional[str],
    cv_text: str,
    job_text: str,
    style_instructions: str,
    structure_instructions: str = "",
    additional_user_info: str = "",
    additional_company_info: str = "",
    company_report: str = "",
    top_docs: Optional[List[Dict[str, Any]]] = None,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
):
    style = (style_instructions or "").strip()
    if not style:
        style = get_user_style_instructions(user_data) or get_style_instructions()

    cache_prefix = build_autocomplete_cache_prefix(
        cv_text=cv_text or "",
        job_text=job_text or "",
        style_instructions=style,
        structure_instructions=structure_instructions or "",
        additional_user_info=additional_user_info or "",
        additional_company_info=additional_company_info or "",
        company_report=company_report or "",
        top_docs=top_docs,
        company_name=company_name or "",
        job_title=job_title or "",
        location=location or "",
        language=language or "",
        salary=salary or "",
        requirements=requirements,
        competences=competences,
        point_of_contact=point_of_contact,
        language_prefix=build_language_system_prefix(user_data or {}, language or ""),
    )

    explicit = str(model_key).strip() if model_key and str(model_key).strip() else None
    resolved_key = resolve_autocomplete_plan_model(user_data, explicit_model=explicit)
    vendor = parse_autocomplete_vendor(resolved_key)
    client = get_client(vendor)
    _reset_client_counters(client)

    model_override = resolved_key.split("/", 1)[1] if "/" in resolved_key else None
    model_role: ModelRole | str = (
        model_override if model_override else ModelRole.AUTOCOMPLETE_PLAN
    )
    return cache_prefix, client, model_role, resolved_key, vendor


def _merge_plans_with_sections(
    sections: List[Dict[str, Any]],
    plans: Dict[str, str],
) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for i, sec in enumerate(sections):
        key = str(i)
        plan = str(plans.get(key) or (sec.get("plan") if isinstance(sec, dict) else "") or "").strip()
        if plan:
            merged[key] = plan
    return merged


def run_autocomplete_plan_context_summary(
    *,
    user_id: str,
    user_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    plans: Dict[str, str],
    model_key: Optional[str] = None,
    cv_text: str,
    job_text: str,
    style_instructions: str,
    additional_user_info: str = "",
    additional_company_info: str = "",
    structure_instructions: str = "",
    company_report: str = "",
    top_docs: Optional[List[Dict[str, Any]]] = None,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """After plans exist, compress full applicant/job context for autocomplete caching."""
    merged_plans = _merge_plans_with_sections(sections, plans)
    if not merged_plans:
        raise ValueError("At least one section plan is required to build context summary")

    cache_prefix, client, model_role, resolved_key, vendor = _autocomplete_plan_client_setup(
        user_data=user_data,
        model_key=model_key,
        cv_text=cv_text,
        job_text=job_text,
        style_instructions=style_instructions,
        structure_instructions=structure_instructions,
        additional_user_info=additional_user_info,
        additional_company_info=additional_company_info,
        company_report=company_report,
        top_docs=top_docs,
        company_name=company_name,
        job_title=job_title,
        location=location,
        language=language,
        salary=salary,
        requirements=requirements,
        competences=competences,
        point_of_contact=point_of_contact,
    )
    max_chars = max(1, len(cache_prefix) // 10) if cache_prefix else 0
    if max_chars <= 0:
        raise ValueError("Cannot build context summary: planning context is empty")

    user_prompt = build_context_summary_user_prompt(sections=sections, plans=merged_plans)
    system = (
        "You are an expert cover letter strategist. "
        "Compress the applicant and job context (system message) into a short summary "
        "that supports executing the section plans in the user message. "
        f"Maximum length: {max_chars} characters (strict — count every character). "
        "Include only facts the plans need; omit irrelevant CV lines, examples, and metadata. "
        "Output only the summary text — no labels, JSON, or commentary."
    )

    raw = client.call(
        model_role,
        system,
        [user_prompt],
        system_cache_prefix=cache_prefix or None,
    )
    summary, warnings = finalize_plan_context_summary(
        raw or "",
        full_context_len=len(cache_prefix),
    )
    if not summary:
        raise ValueError(
            "Planning model returned an empty context summary"
            + (f" ({'; '.join(warnings)})" if warnings else "")
        )

    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    cached_tokens = int(getattr(client, "total_cached_tokens", 0) or 0)

    if cost > 0:
        track_api_cost(
            user_id,
            "autocomplete_plan_summary",
            vendor.value,
            cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens if cached_tokens else None,
        )

    out: Dict[str, Any] = {
        "context_summary": summary,
        "model_used": resolved_key,
        "cost": cost,
        "cached_tokens": cached_tokens,
        "context_summary_max_chars": max_chars,
    }
    if warnings:
        out["context_summary_warnings"] = warnings
    return out


def run_autocomplete_all_sections_plan(
    *,
    user_id: str,
    user_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    model_key: Optional[str] = None,
    cv_text: str,
    job_text: str,
    style_instructions: str,
    additional_user_info: str = "",
    additional_company_info: str = "",
    structure_instructions: str = "",
    company_report: str = "",
    top_docs: Optional[List[Dict[str, Any]]] = None,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One LLM call: tactical plans for all sections with non-overlapping goals."""
    if not sections:
        raise ValueError("sections are required for planning")

    cache_prefix, client, model_role, resolved_key, vendor = _autocomplete_plan_client_setup(
        user_data=user_data,
        model_key=model_key,
        cv_text=cv_text,
        job_text=job_text,
        style_instructions=style_instructions,
        structure_instructions=structure_instructions,
        additional_user_info=additional_user_info,
        additional_company_info=additional_company_info,
        company_report=company_report,
        top_docs=top_docs,
        company_name=company_name,
        job_title=job_title,
        location=location,
        language=language,
        salary=salary,
        requirements=requirements,
        competences=competences,
        point_of_contact=point_of_contact,
    )

    summary_budget = context_summary_max_chars(len(cache_prefix)) if cache_prefix else 0
    user_prompt = build_all_sections_plan_user_prompt(
        sections=sections,
        context_summary_max_chars=summary_budget,
    )
    system = (
        "You are an expert cover letter strategist. "
        "Given the applicant CV, target job, and letter structure, plan every section at once "
        "and compress the context needed to execute those plans. "
        "Each section gets 3–5 markdown bullets (tactical outline only) "
        "and a hidden full draft of that section's letter text (complete paragraphs, not an overview). "
        "Bullets must not overlap across sections. "
        "Bridge gaps honestly; use the job description language for skills and facts. "
        "Respond with JSON only as specified in the user message (plans, proposals, context_summary)."
    )

    raw = client.call(
        model_role,
        system,
        [user_prompt],
        system_cache_prefix=cache_prefix or None,
    )
    plans, proposals, summary_raw = parse_autocomplete_plan_batch_json(
        raw or "", expected_count=len(sections)
    )
    context_summary, context_summary_warnings = finalize_plan_context_summary(
        summary_raw,
        full_context_len=len(cache_prefix),
    )
    if not context_summary:
        raise ValueError(
            "Planning model returned an empty context_summary"
            + (
                f" ({'; '.join(context_summary_warnings)})"
                if context_summary_warnings
                else ""
            )
        )

    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    cached_tokens = int(getattr(client, "total_cached_tokens", 0) or 0)

    if cost > 0:
        track_api_cost(
            user_id,
            "autocomplete_plan",
            vendor.value,
            cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens if cached_tokens else None,
        )

    out: Dict[str, Any] = {
        "plans": plans,
        "proposals": proposals,
        "context_summary": context_summary,
        "model_used": resolved_key,
        "cost": cost,
        "cached_tokens": cached_tokens,
        "context_summary_max_chars": summary_budget,
    }
    if context_summary_warnings:
        out["context_summary_warnings"] = context_summary_warnings
    return out


def run_autocomplete_section_plan(
    *,
    user_id: str,
    user_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    section_index: int,
    model_key: Optional[str] = None,
    cv_text: str,
    job_text: str,
    style_instructions: str,
    additional_user_info: str = "",
    additional_company_info: str = "",
    structure_instructions: str = "",
    company_report: str = "",
    top_docs: Optional[List[Dict[str, Any]]] = None,
    company_name: str = "",
    job_title: str = "",
    location: str = "",
    language: str = "",
    salary: str = "",
    requirements: Optional[List[str]] = None,
    competences: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """LLM tactical plan for one section; siblings may include goal + plan for de-duplication."""
    if not sections:
        raise ValueError("sections are required for planning")

    cache_prefix, client, model_role, resolved_key, vendor = _autocomplete_plan_client_setup(
        user_data=user_data,
        model_key=model_key,
        cv_text=cv_text,
        job_text=job_text,
        style_instructions=style_instructions,
        structure_instructions=structure_instructions,
        additional_user_info=additional_user_info,
        additional_company_info=additional_company_info,
        company_report=company_report,
        top_docs=top_docs,
        company_name=company_name,
        job_title=job_title,
        location=location,
        language=language,
        salary=salary,
        requirements=requirements,
        competences=competences,
        point_of_contact=point_of_contact,
    )

    user_prompt = build_section_plan_user_prompt(
        sections=sections, section_index=section_index
    )
    system = (
        "You are an expert cover letter strategist. "
        "Given the applicant CV, target job, and letter structure, produce a tactical plan "
        "for ONE section: 3–5 markdown bullet points plus a hidden full draft of that section's letter text. "
        "Respect other sections' existing plans and proposals — do not repeat content assigned elsewhere. "
        "Bullets are tactical only; the proposal is the complete cover-letter wording for this section "
        "(real paragraphs, not an overview or notes about what to write). "
        "Bridge gaps honestly (e.g. related languages or transferable skills). "
        "Use the same language as the job description when naming skills or facts."
    )

    raw = client.call(
        model_role,
        system,
        [user_prompt],
        system_cache_prefix=cache_prefix or None,
    )
    plan_text, proposal_text = parse_autocomplete_section_plan_response(raw or "")
    idx = max(0, min(section_index, len(sections) - 1))
    plans_for_summary = _merge_plans_with_sections(
        sections, {str(idx): plan_text}
    )

    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    cached_tokens = int(getattr(client, "total_cached_tokens", 0) or 0)

    if cost > 0:
        track_api_cost(
            user_id,
            "autocomplete_plan",
            vendor.value,
            cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens if cached_tokens else None,
        )

    summary_result = run_autocomplete_plan_context_summary(
        user_id=user_id,
        user_data=user_data,
        sections=sections,
        plans=plans_for_summary,
        model_key=model_key,
        cv_text=cv_text,
        job_text=job_text,
        style_instructions=style_instructions,
        structure_instructions=structure_instructions,
        additional_user_info=additional_user_info,
        additional_company_info=additional_company_info,
        company_report=company_report,
        top_docs=top_docs,
        company_name=company_name,
        job_title=job_title,
        location=location,
        language=language,
        salary=salary,
        requirements=requirements,
        competences=competences,
        point_of_contact=point_of_contact,
    )
    total_cost = cost + float(summary_result.get("cost", 0.0) or 0.0)

    out: Dict[str, Any] = {
        "plan_text": plan_text,
        "proposal_text": proposal_text,
        "section_index": idx,
        "context_summary": summary_result.get("context_summary", ""),
        "model_used": resolved_key,
        "cost": total_cost,
        "cached_tokens": cached_tokens,
    }
    if summary_result.get("context_summary_warnings"):
        out["context_summary_warnings"] = summary_result["context_summary_warnings"]
    return out
