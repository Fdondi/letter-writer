"""Autocomplete flow API."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from letter_writer.autocomplete_core import (
    build_autocomplete_draft_prefix,
    get_autocomplete_plan_role_defaults,
    get_autocomplete_role_defaults,
    next_model_in_cycle,
    resolve_autocomplete_model,
    resolve_autocomplete_plan_model,
)
from letter_writer.autocomplete_service import (
    run_autocomplete_all_sections_plan,
    run_autocomplete_completion,
    run_autocomplete_section_plan,
)
from letter_writer.firestore_store import get_user_data
from letter_writer.generation import get_style_instructions
from letter_writer.personal_data_sections import (
    get_autocomplete_ctrl_letter_map,
    get_autocomplete_max_words,
    get_autocomplete_models,
    get_autocomplete_plan_model,
    get_autocomplete_stop_on_period,
    get_structure_instructions as get_user_structure_instructions,
    get_style_instructions as get_user_style_instructions,
)
from letter_writer.session_store import log_user_input_event, set_current_request
from letter_writer_server.api.cost_utils import check_spending_limits, with_user_monthly_cost
from letter_writer_server.core.session import Session, get_session, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)


class AutocompleteSection(BaseModel):
    title: str = ""
    description: str = ""
    body: str = ""
    plan: str = ""
    proposal: str = ""


class AutocompleteCompleteRequest(BaseModel):
    text: str = ""
    cursor: Optional[int] = None
    sections: Optional[List[AutocompleteSection]] = None
    active_section_index: Optional[int] = Field(default=None, ge=0)
    cursor_in_section: Optional[int] = Field(default=None, ge=0)
    model: Optional[str] = None
    ctrl_letter: Optional[str] = Field(default=None, max_length=1)
    shift_letter: Optional[str] = Field(default=None, max_length=1)
    cycle_next: bool = False
    max_words: Optional[int] = Field(default=None, ge=1, le=100)
    stop_on_period: Optional[bool] = None
    job_text: Optional[str] = None
    additional_user_info: Optional[str] = None
    additional_company_info: Optional[str] = None
    style_instructions: Optional[str] = None
    structure_instructions: Optional[str] = None
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    location: Optional[str] = None
    language: Optional[str] = None
    salary: Optional[str] = None
    requirements: Optional[List[str]] = None
    competences: Optional[Dict[str, Any]] = None
    point_of_contact: Optional[Dict[str, Any]] = None
    context_summary: Optional[str] = None
    active_section_plan: Optional[str] = None
    active_section_proposal: Optional[str] = None
    section_proposal_stale: bool = False
    cache_offset: int = Field(default=0, ge=0)
    extend_cache: bool = False


class AutocompletePlanRequest(BaseModel):
    sections: List[AutocompleteSection]
    section_index: Optional[int] = Field(default=None, ge=0)
    plan_all: bool = False
    plan_model: Optional[str] = None
    job_text: Optional[str] = None
    additional_user_info: Optional[str] = None
    additional_company_info: Optional[str] = None
    style_instructions: Optional[str] = None
    structure_instructions: Optional[str] = None
    company_report: Optional[str] = None
    top_docs: Optional[List[Dict[str, Any]]] = None
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    location: Optional[str] = None
    language: Optional[str] = None
    salary: Optional[str] = None
    requirements: Optional[List[str]] = None
    competences: Optional[Dict[str, Any]] = None
    point_of_contact: Optional[Dict[str, Any]] = None


def _session_common(session: Session) -> Dict[str, Any]:
    metadata = session.get("metadata") or {}
    common = metadata.get("common") if isinstance(metadata, dict) else {}
    return common if isinstance(common, dict) else {}


def _resolve_str(request_val: Optional[str], *fallbacks: Any) -> str:
    if request_val is not None:
        return str(request_val)
    for fb in fallbacks:
        if fb is not None and str(fb).strip():
            return str(fb)
    return ""


def _resolve_list(request_val: Optional[List[str]], fallback: Any) -> List[str]:
    if request_val is not None:
        return [str(r).strip() for r in request_val if str(r).strip()]
    if isinstance(fallback, list):
        return [str(r).strip() for r in fallback if str(r).strip()]
    return []


def _resolve_dict(request_val: Optional[Dict[str, Any]], fallback: Any) -> Optional[Dict[str, Any]]:
    if request_val is not None:
        return request_val if isinstance(request_val, dict) else None
    if isinstance(fallback, dict) and fallback:
        return fallback
    return None


def _ensure_session_cv(session: Session, user_id: str) -> None:
    if session.get("cv_text"):
        return
    user_data = get_user_data(user_id, use_cache=True) or {}
    from letter_writer.personal_data_sections import cv_text_with_extra_info, get_cv_revisions

    cv_revisions = get_cv_revisions(user_data)
    if cv_revisions:
        latest = max(cv_revisions, key=lambda x: x.get("created_at", ""))
        base_cv = latest.get("content", "")
        session["cv_text"] = cv_text_with_extra_info(base_cv, user_data)


@router.post("/complete/")
def autocomplete_complete(
    data: AutocompleteCompleteRequest,
    request: Request,
    session: Session = Depends(get_session),
    _limit: None = Depends(check_spending_limits),
):
    set_current_request(request)
    log_user_input_event("autocomplete.complete", data.dict(exclude_none=True))

    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = user["id"]
    _ensure_session_cv(session, user_id)

    user_data = get_user_data(user_id, use_cache=True) or {}
    common = _session_common(session)

    text_before_cursor = ""
    if data.sections:
        section_dicts = [s.dict() for s in data.sections]
        active_idx = data.active_section_index if data.active_section_index is not None else 0
        active_idx = max(0, min(active_idx, len(section_dicts) - 1))
        active_body = section_dicts[active_idx].get("body") or ""
        cur_in_sec = (
            data.cursor_in_section
            if data.cursor_in_section is not None
            else len(active_body)
        )
        cur_in_sec = max(0, min(cur_in_sec, len(active_body)))
        text_before_cursor = active_body[:cur_in_sec]
        prefix = build_autocomplete_draft_prefix(section_dicts, active_idx, cur_in_sec)
    else:
        full_text = data.text or ""
        cursor = data.cursor if data.cursor is not None else len(full_text)
        cursor = max(0, min(cursor, len(full_text)))
        text_before_cursor = full_text[:cursor]
        prefix = text_before_cursor

    if data.cycle_next and data.model:
        raise HTTPException(
            status_code=400,
            detail="Provide either model or cycle_next, not both.",
        )

    if data.model:
        model_key = resolve_autocomplete_model(user_data, explicit_model=data.model)
    elif data.ctrl_letter or data.shift_letter:
        model_key = resolve_autocomplete_model(
            user_data,
            ctrl_letter=data.ctrl_letter or data.shift_letter,
        )
    elif data.cycle_next:
        current = resolve_autocomplete_model(user_data)
        model_key = next_model_in_cycle(current, user_data)
    else:
        model_key = resolve_autocomplete_model(user_data)

    job_text = _resolve_str(data.job_text, session.get("job_text"))
    additional_user_info = _resolve_str(
        data.additional_user_info, common.get("additional_user_info")
    )
    additional_company_info = _resolve_str(
        data.additional_company_info, common.get("additional_company_info")
    )
    structure = _resolve_str(
        data.structure_instructions,
        session.get("structure_instructions"),
        get_user_structure_instructions(user_data),
    )
    style = _resolve_str(
        data.style_instructions,
        session.get("style_instructions"),
        get_user_style_instructions(user_data),
        get_style_instructions(),
    )
    company_report = _resolve_str(data.company_report)
    top_docs = data.top_docs if data.top_docs is not None else (session.get("selected_top_docs") or [])

    company_name = _resolve_str(data.company_name, common.get("company_name"))
    job_title = _resolve_str(data.job_title, common.get("job_title"))
    location = _resolve_str(data.location, common.get("location"))
    language = _resolve_str(data.language, common.get("language"))
    salary = _resolve_str(data.salary, common.get("salary"))
    requirements = _resolve_list(data.requirements, common.get("requirements"))
    competences = _resolve_dict(data.competences, common.get("competences"))
    point_of_contact = _resolve_dict(data.point_of_contact, common.get("point_of_contact"))
    context_summary = _resolve_str(data.context_summary)
    active_section_plan = _resolve_str(data.active_section_plan)
    active_section_proposal = _resolve_str(data.active_section_proposal)
    section_proposal_stale = bool(data.section_proposal_stale)

    try:
        result = run_autocomplete_completion(
            user_id=user_id,
            user_data=user_data,
            prefix=prefix,
            model_key=model_key,
            cv_text=session.get("cv_text") or "",
            job_text=job_text,
            style_instructions=style,
            structure_instructions=structure,
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
            max_words=data.max_words,
            stop_on_period=data.stop_on_period,
            allow_memo=not data.cycle_next,
            plan_context_summary=context_summary,
            active_section_plan=active_section_plan,
            active_section_proposal=active_section_proposal,
            section_proposal_stale=section_proposal_stale,
            text_before_cursor=text_before_cursor,
            cache_offset=data.cache_offset,
            extend_cache=data.extend_cache,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("autocomplete complete failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    payload: Dict[str, Any] = {
        "status": "ok",
        "suggestion_text": result.get("suggestion_text", ""),
        "model_used": result.get("model_used", model_key),
        "cost": result.get("cost", 0.0),
        "cached_tokens": result.get("cached_tokens", 0),
        "truncated_by": result.get("truncated_by"),
        "cache_hit": result.get("cache_hit", False),
        "max_words": result.get("max_words"),
        "stop_on_period": result.get("stop_on_period"),
        "cache_prefix": result.get("cache_prefix") or "",
        "cache_offset": result.get("cache_offset", 0),
        "cache_offset_next": result.get("cache_offset_next", 0),
        "cache_has_more": result.get("cache_has_more", False),
        "extend_cache_recommended": result.get("extend_cache_recommended", False),
    }
    if result.get("warnings"):
        payload["warnings"] = result["warnings"]
    if result.get("raw_suggestion_text"):
        payload["raw_suggestion_text"] = result["raw_suggestion_text"]
    return with_user_monthly_cost(payload, session)


def _resolve_autocomplete_context(
    data: Any,
    session: Session,
    user_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Shared job/CV/style resolution for autocomplete complete and plan endpoints."""
    common = _session_common(session)
    return {
        "job_text": _resolve_str(getattr(data, "job_text", None), session.get("job_text")),
        "additional_user_info": _resolve_str(
            getattr(data, "additional_user_info", None), common.get("additional_user_info")
        ),
        "additional_company_info": _resolve_str(
            getattr(data, "additional_company_info", None), common.get("additional_company_info")
        ),
        "structure": _resolve_str(
            getattr(data, "structure_instructions", None),
            session.get("structure_instructions"),
            get_user_structure_instructions(user_data),
        ),
        "style": _resolve_str(
            getattr(data, "style_instructions", None),
            session.get("style_instructions"),
            get_user_style_instructions(user_data),
            get_style_instructions(),
        ),
        "company_report": _resolve_str(getattr(data, "company_report", None)),
        "top_docs": getattr(data, "top_docs", None)
        if getattr(data, "top_docs", None) is not None
        else (session.get("selected_top_docs") or []),
        "company_name": _resolve_str(getattr(data, "company_name", None), common.get("company_name")),
        "job_title": _resolve_str(getattr(data, "job_title", None), common.get("job_title")),
        "location": _resolve_str(getattr(data, "location", None), common.get("location")),
        "language": _resolve_str(getattr(data, "language", None), common.get("language")),
        "salary": _resolve_str(getattr(data, "salary", None), common.get("salary")),
        "requirements": _resolve_list(getattr(data, "requirements", None), common.get("requirements")),
        "competences": _resolve_dict(getattr(data, "competences", None), common.get("competences")),
        "point_of_contact": _resolve_dict(
            getattr(data, "point_of_contact", None), common.get("point_of_contact")
        ),
    }


@router.post("/plan/")
def autocomplete_plan(
    data: AutocompletePlanRequest,
    request: Request,
    session: Session = Depends(get_session),
    _limit: None = Depends(check_spending_limits),
):
    set_current_request(request)
    log_user_input_event("autocomplete.plan", data.dict(exclude_none=True))

    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = user["id"]
    _ensure_session_cv(session, user_id)
    user_data = get_user_data(user_id, use_cache=True) or {}

    if not data.sections:
        raise HTTPException(status_code=400, detail="sections are required")

    section_dicts = [s.dict() for s in data.sections]
    ctx = _resolve_autocomplete_context(data, session, user_data)
    plan_model = resolve_autocomplete_plan_model(
        user_data, explicit_model=data.plan_model
    )

    plan_kwargs = dict(
        user_id=user_id,
        user_data=user_data,
        sections=section_dicts,
        model_key=plan_model,
        cv_text=session.get("cv_text") or "",
        job_text=ctx["job_text"],
        style_instructions=ctx["style"],
        structure_instructions=ctx["structure"],
        additional_user_info=ctx["additional_user_info"],
        additional_company_info=ctx["additional_company_info"],
        company_report=ctx["company_report"],
        top_docs=ctx["top_docs"],
        company_name=ctx["company_name"],
        job_title=ctx["job_title"],
        location=ctx["location"],
        language=ctx["language"],
        salary=ctx["salary"],
        requirements=ctx["requirements"],
        competences=ctx["competences"],
        point_of_contact=ctx["point_of_contact"],
    )

    plans: Dict[str, str] = {}
    proposals: Dict[str, str] = {}
    context_summary = ""
    context_summary_warnings: List[str] = []
    total_cost = 0.0
    model_used = plan_model

    try:
        if data.plan_all:
            result = run_autocomplete_all_sections_plan(**plan_kwargs)
            plans = result.get("plans") or {}
            proposals = result.get("proposals") or {}
            context_summary = str(result.get("context_summary") or "")
            context_summary_warnings = list(result.get("context_summary_warnings") or [])
            total_cost = float(result.get("cost", 0.0) or 0.0)
            model_used = result.get("model_used", model_used)
        else:
            if data.section_index is not None:
                idx = max(0, min(data.section_index, len(section_dicts) - 1))
            else:
                idx = 0
            result = run_autocomplete_section_plan(**plan_kwargs, section_index=idx)
            plans[str(idx)] = result.get("plan_text", "")
            proposals[str(idx)] = result.get("proposal_text", "")
            context_summary = str(result.get("context_summary") or "")
            context_summary_warnings = list(result.get("context_summary_warnings") or [])
            total_cost = float(result.get("cost", 0.0) or 0.0)
            model_used = result.get("model_used", model_used)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("autocomplete plan failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    payload: Dict[str, Any] = {
        "status": "ok",
        "plans": plans,
        "proposals": proposals,
        "context_summary": context_summary,
        "model_used": model_used,
        "cost": total_cost,
    }
    if context_summary_warnings:
        payload["context_summary_warnings"] = context_summary_warnings
    return with_user_monthly_cost(payload, session)


@router.get("/settings/")
def autocomplete_settings(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_data = get_user_data(user["id"], use_cache=True) or {}
    models = get_autocomplete_models(user_data)
    return {
        "status": "ok",
        "autocomplete_max_words": get_autocomplete_max_words(user_data),
        "autocomplete_stop_on_period": get_autocomplete_stop_on_period(user_data),
        "autocomplete_models": models,
        "autocomplete_ctrl_letter_map": get_autocomplete_ctrl_letter_map(user_data),
        "autocomplete_shift_letter_map": get_autocomplete_ctrl_letter_map(user_data),
        "autocomplete_role_defaults": get_autocomplete_role_defaults(),
        "autocomplete_plan_role_defaults": get_autocomplete_plan_role_defaults(),
        "autocomplete_plan_model": get_autocomplete_plan_model(user_data),
        "autocomplete_default_model": models[0] if models else resolve_autocomplete_model(user_data),
    }
