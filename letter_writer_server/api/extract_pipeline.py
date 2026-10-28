"""Shared job-extraction orchestration used by /api/extract/ and job-capture process."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException
from openai import OpenAI

from letter_writer.generation import (
    DEFAULT_NEED_SEMANTICS,
    LEVEL_LABELS,
    extract_key_competences,
    grade_competence_cv_match,
    _level_label_for_rating,
)
from letter_writer.firestore_store import get_collection, get_user_data
from letter_writer.headless import latest_cv_text
from letter_writer.personal_data_sections import get_competence_ratings
from letter_writer.retrieval import retrieve_similar_job_offers, select_top_documents, sanitize_search_results
from letter_writer_server.core.session import Session

logger = logging.getLogger(__name__)


def resolve_cv_for_extract(session: Session) -> tuple[str, Dict[str, Any], str]:
    """Load CV text and user_data. Raises 400 if CV is missing."""
    user = session.get("user")
    user_id = (user or {}).get("id") or "anonymous"
    cv_text = session.get("cv_text", "")
    user_data: Dict[str, Any] = {}
    if not cv_text and user:
        user_data = get_user_data(user["id"], use_cache=True)
        if user_data.get("cv_revisions"):
            session["cv_text"] = latest_cv_text(user_data)
    elif user:
        user_data = get_user_data(user["id"], use_cache=True)

    cv_text = session.get("cv_text", "")
    if not cv_text:
        raise HTTPException(status_code=400, detail="CV text is missing")
    return cv_text, user_data, user_id


def run_extract_pipeline(
    *,
    competence_source_text: str,
    similar_job_text: Optional[str] = None,
    page_metadata_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    session: Session,
    scale_cfg: Optional[Dict[str, Any]],
    user_data: Dict[str, Any],
    cv_text: str,
    user_id: str,
    ai_client,
) -> Dict[str, Any]:
    """Extract competences (from competence_source_text), similar jobs (from cleaned job text).

    When ``page_metadata_fn`` is set it runs in parallel with competence extraction and
    supplies cleaned ``job_text`` plus company/title fields. RAG waits for that job_text.
    Job-capture passes template-focused posting text as competence_source_text when a
    hostname template matched.
    """
    collection = get_collection()
    openai_client = OpenAI()
    trace_dir = Path("trace", "extraction.openai")
    scale_cfg = scale_cfg or {}
    need_semantics = {**DEFAULT_NEED_SEMANTICS, **(scale_cfg.get("needSemantics") or {})}
    need_labels = tuple(need_semantics.keys())
    level_cfg = scale_cfg.get("level") or {}
    level_labels = tuple(level_cfg.keys()) if level_cfg else LEVEL_LABELS
    default_lvl = "Brief experience" if "Brief experience" in level_labels else level_labels[len(level_labels) // 2]

    def _phase1_extract_competences():
        return extract_key_competences(
            competence_source_text,
            ai_client,
            Path(trace_dir, "competences"),
            need_categories=need_labels,
            need_semantics=need_semantics,
        )

    def _phase2_grade(unmatched):
        if not unmatched:
            return {}
        grade_job = similar_job_text or competence_source_text
        return grade_competence_cv_match(
            unmatched,
            cv_text,
            grade_job,
            ai_client,
            Path(trace_dir, "grade_cv_match"),
            level_labels=level_labels,
        )

    def _process_competences(competences_by_cat):
        flat_pairs = []
        seen = set()
        for cat in need_labels:
            for skill in competences_by_cat.get(cat, []):
                if skill and skill not in seen:
                    seen.add(skill)
                    flat_pairs.append((skill, cat))
        for cat, skills in competences_by_cat.items():
            if cat in need_labels:
                continue
            for skill in skills:
                if skill and skill not in seen:
                    seen.add(skill)
                    flat_pairs.append((skill, cat))

        existing = get_competence_ratings(user_data) or user_data.get("competence_ratings") or {}
        existing_lookup = {}
        for k, v in existing.items():
            if isinstance(v, (int, float)) and 1 <= v <= 5:
                norm = " ".join((k or "").strip().lower().split())
                if norm:
                    existing_lookup[norm] = int(round(v))

        matched_levels = {}
        unmatched = []
        for skill, _need in flat_pairs:
            norm_skill = " ".join((skill or "").strip().lower().split())
            if norm_skill in existing_lookup:
                matched_levels[skill] = _level_label_for_rating(
                    level_labels, level_cfg, existing_lookup[norm_skill]
                )
            else:
                unmatched.append(skill)
        return flat_pairs, matched_levels, unmatched

    page_meta: Dict[str, Any] = dict(extra_metadata or {})
    rag_query_text = (similar_job_text or "").strip()

    similar_documents = []
    top_docs = []
    flat_pairs = []
    matched_levels: Dict[str, str] = {}
    hire_problem = ""
    all_scores: Dict[str, Any] = {}
    all_briefs: Dict[str, Any] = {}
    score_details: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        pending: Dict[Any, str] = {}
        competences_future = executor.submit(_phase1_extract_competences)
        pending[competences_future] = "competences"

        if page_metadata_fn is not None:
            page_future = executor.submit(page_metadata_fn)
            pending[page_future] = "page"
        elif rag_query_text:
            rag_future = executor.submit(
                retrieve_similar_job_offers,
                rag_query_text,
                collection,
                openai_client,
                user_id,
            )
            pending[rag_future] = "rag"

        not_done = set(pending.keys())
        while not_done:
            done, not_done = wait(not_done, return_when=FIRST_COMPLETED)
            for fut in done:
                tag = pending[fut]
                if tag == "competences":
                    competences_by_cat, hire_problem = fut.result()
                    logger.info("[EXTRACT] Competences extracted, submitting grading")
                    flat_pairs, matched_levels, unmatched = _process_competences(competences_by_cat)
                    grade_future = executor.submit(_phase2_grade, unmatched)
                    pending[grade_future] = "grade"
                    not_done.add(grade_future)
                elif tag == "page":
                    result = fut.result() or {}
                    if isinstance(result, dict):
                        page_meta.update(result)
                    rag_query_text = str(page_meta.get("job_text") or competence_source_text).strip()
                    logger.info("[EXTRACT] Page metadata extracted, submitting RAG")
                    rag_future = executor.submit(
                        retrieve_similar_job_offers,
                        rag_query_text,
                        collection,
                        openai_client,
                        user_id,
                    )
                    pending[rag_future] = "rag"
                    not_done.add(rag_future)
                elif tag == "rag":
                    try:
                        raw_similar = fut.result()
                        logger.info("[EXTRACT] RAG search returned %s raw results", len(raw_similar))
                        similar_documents = sanitize_search_results(raw_similar)
                        if raw_similar:
                            rerank_trace = Path("trace", "extraction.rerank")
                            rerank_trace.mkdir(parents=True, exist_ok=True)
                            rerank_job = rag_query_text or competence_source_text
                            rerank_future = executor.submit(
                                select_top_documents,
                                raw_similar,
                                rerank_job,
                                ai_client,
                                rerank_trace,
                            )
                            pending[rerank_future] = "rerank"
                            not_done.add(rerank_future)
                    except Exception as rag_err:
                        logger.exception(
                            "[EXTRACT] RAG search failed: %s: %s",
                            type(rag_err).__name__,
                            rag_err,
                        )
                elif tag == "grade":
                    llm_levels = fut.result()
                    logger.info("[EXTRACT] CV grading complete")
                    for skill in [s for s, _ in flat_pairs]:
                        if skill not in matched_levels:
                            matched_levels[skill] = llm_levels.get(skill, default_lvl)
                elif tag == "rerank":
                    try:
                        result = fut.result()
                        top_docs = result["top_docs"]
                        all_scores = result.get("all_scores", {})
                        all_briefs = result.get("all_briefs", {})
                        score_details = result.get("score_details", {}) or {}
                        logger.info("[EXTRACT] LLM reranking selected %s top docs", len(top_docs))
                    except Exception as rerank_err:
                        logger.warning("[EXTRACT] LLM reranking failed: %s", rerank_err)

    levels = dict(matched_levels)
    extraction = {
        "competences": {
            skill: {"need": need, "level": levels.get(skill, default_lvl)}
            for skill, need in flat_pairs
        },
        "requirements": [s for s, _ in flat_pairs],
        "hire_problem": hire_problem or "",
    }
    for key in (
        "company_name",
        "job_title",
        "location",
        "language",
        "salary",
        "point_of_contact",
        "additional_company_info",
    ):
        if page_meta.get(key) not in (None, ""):
            extraction[key] = page_meta[key]
    source_url = str(page_meta.get("source_url") or "").strip()
    if source_url:
        extraction["source_url"] = source_url

    cleaned_job_text = str(page_meta.get("job_text") or rag_query_text or competence_source_text)

    for doc in similar_documents:
        company = (doc.get("company_name_original") or doc.get("company_name") or "").strip()
        if company and company in all_scores:
            doc["score"] = all_scores[company]
        if company and company in score_details:
            for key, value in (score_details[company] or {}).items():
                doc[key] = value
        if company and company in all_briefs:
            brief = all_briefs[company] or {}
            doc["similarities"] = brief.get("similarities", [])
            doc["differences"] = brief.get("differences", [])

    metadata = dict(session.get("metadata") or {})
    common = dict(metadata.get("common") or {})
    common.update(extraction)
    metadata["common"] = common
    session["metadata"] = metadata
    session["job_text"] = cleaned_job_text

    logger.info(
        "[EXTRACT] Returning %s similar_documents, %s top_docs",
        len(similar_documents),
        len(top_docs),
    )
    return {
        "extraction": extraction,
        "similar_documents": similar_documents,
        "top_docs": top_docs,
        "job_text": cleaned_job_text,
        "session_id": session.session_key,
    }


def run_capture_extract(
    session: Session,
    *,
    visible_text: str,
    html: str,
    source_url: str,
    scale_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract a captured job page into ``session`` (job text, metadata, similar letters).

    Shared by ``/api/job-capture/{id}/process/`` and the opportunity batch. Records the
    extraction cost and adds ``source_url`` to the result.
    """
    # misc imports this module; import its helpers here to avoid the cycle.
    from letter_writer.client import get_extraction_client
    from letter_writer.generation import extract_job_page_metadata
    from letter_writer.page_templates import extract_from_captured_page
    from letter_writer_server.api.misc import _reset_client_counters, _track_and_reset_client_cost

    parsed_page = extract_from_captured_page(html, source_url)
    focused_text = str(parsed_page.get("job_text") or "").strip()
    competence_source_text = focused_text or visible_text or html
    canonical_url = str(parsed_page.get("source_url") or "").strip() or source_url

    cv_text, user_data, user_id = resolve_cv_for_extract(session)
    extract_vendor, ai_client = get_extraction_client(user_data)
    _reset_client_counters(ai_client)
    trace_dir = Path("trace", "extraction.page_capture")

    def _page_metadata():
        meta = extract_job_page_metadata(
            visible_text,
            ai_client,
            html=html,
            source_url=source_url,
            trace_dir=trace_dir,
            parsed_page=parsed_page,
        )
        if canonical_url:
            meta["source_url"] = str(meta.get("source_url") or "").strip() or canonical_url
        return meta

    result = run_extract_pipeline(
        competence_source_text=competence_source_text,
        similar_job_text=None,
        page_metadata_fn=_page_metadata,
        session=session,
        scale_cfg=scale_cfg,
        user_data=user_data,
        cv_text=cv_text,
        user_id=user_id,
        ai_client=ai_client,
    )
    _track_and_reset_client_cost(
        user_id=user_id,
        phase="extract",
        vendor=extract_vendor.value,
        client=ai_client,
    )
    result["source_url"] = str((result.get("extraction") or {}).get("source_url") or canonical_url)
    return result
