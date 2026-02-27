import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from letter_writer_server.core.session import Session, get_session
from letter_writer.client import get_client, ModelVendor
from letter_writer.generation import (
    extract_key_competences,
    grade_competence_cv_match,
    MissingCVError,
    get_style_instructions,
    LEVEL_LABELS,
    DEFAULT_NEED_SEMANTICS,
)
from letter_writer.service import write_cover_letter, refresh_repository
from letter_writer.firestore_store import get_collection, upsert_document, get_user_data
from letter_writer.retrieval import embed, retrieve_similar_job_offers, select_top_documents, sanitize_search_results
from letter_writer.personal_data_sections import get_models
from letter_writer.spam_prevention import get_in_flight_requests, clear_in_flight_requests
from letter_writer_server.api.cost_utils import with_user_monthly_cost
from openai import OpenAI

router = APIRouter()
logger = logging.getLogger(__name__)

class ExtractRequest(BaseModel):
    job_text: str
    scale_config: Optional[Dict[str, Any]] = None

class ProcessJobRequest(BaseModel):
    job_text: str
    cv_text: Optional[str] = None
    company_name: Optional[str] = None
    model_vendor: Optional[str] = None
    refine: bool = False
    fancy: bool = False

class RefreshRequest(BaseModel):
    jobs_source_folder: Optional[str] = None
    jobs_source_suffix: Optional[str] = None
    letters_source_folder: Optional[str] = None
    letters_source_suffix: Optional[str] = None
    letters_ignore_until: Optional[str] = None
    letters_ignore_after: Optional[str] = None
    negative_letters_source_folder: Optional[str] = None
    negative_letters_source_suffix: Optional[str] = None
    clear: bool = False

@router.post("/refresh/")
async def refresh(request: Request, data: RefreshRequest):
    try:
        kwargs = data.dict(exclude_unset=True)
        # Convert path strings to Path objects if needed by refresh_repository
        if "jobs_source_folder" in kwargs: kwargs["jobs_source_folder"] = Path(kwargs["jobs_source_folder"])
        if "letters_source_folder" in kwargs: kwargs["letters_source_folder"] = Path(kwargs["letters_source_folder"])
        if "negative_letters_source_folder" in kwargs: kwargs["negative_letters_source_folder"] = Path(kwargs["negative_letters_source_folder"])
        
        refresh_repository(**kwargs, logger=logger.info)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/extract/")
async def extract_job(request: Request, data: ExtractRequest, session: Session = Depends(get_session)):
    """User-bound extraction: skills + CV match + similar past jobs, all in parallel."""
    user = session.get('user')
    try:
        ai_client = get_client(ModelVendor.OPENAI)
        trace_dir = Path("trace", "extraction.openai")

        user_id = (user or {}).get("id") or None

        cv_text = session.get('cv_text', "")
        user_data = {}
        if not cv_text and user:
            user_data = get_user_data(user['id'], use_cache=True)
            cv_revisions = user_data.get('cv_revisions', [])
            if cv_revisions:
                sorted_revs = sorted(cv_revisions, key=lambda x: x.get('created_at', ''), reverse=True)
                cv_text = sorted_revs[0].get('content', '')
                session['cv_text'] = cv_text
        elif user:
            user_data = get_user_data(user['id'], use_cache=True)

        if not cv_text:
            raise HTTPException(status_code=400, detail="CV text is missing")

        collection = get_collection()
        openai_client = OpenAI()

        logger.info("[EXTRACT] Start: job_text length=%s", len(data.job_text))

        # --- Phase 1: extract competences (LLM call) --------------------------------
        scale_cfg = data.scale_config or {}
        need_semantics = {**DEFAULT_NEED_SEMANTICS, **(scale_cfg.get("needSemantics") or {})}
        need_labels = tuple(need_semantics.keys())
        level_cfg = scale_cfg.get("level") or {}
        level_labels = tuple(level_cfg.keys()) if level_cfg else LEVEL_LABELS
        default_lvl = "Brief experience" if "Brief experience" in level_labels else level_labels[len(level_labels) // 2]

        def _phase1_extract_competences():
            return extract_key_competences(
                data.job_text,
                ai_client,
                Path(trace_dir, "competences"),
                need_categories=need_labels,
                need_semantics=need_semantics,
            )

        # --- Phase 2: grade unmatched skills against CV (LLM call) -----------------
        def _phase2_grade(flat_pairs, unmatched):
            if not unmatched:
                return {}
            return grade_competence_cv_match(
                unmatched,
                cv_text,
                data.job_text,
                ai_client,
                Path(trace_dir, "grade_cv_match"),
                level_labels=level_labels,
            )

        # --- Process competences into matched/unmatched (pure CPU, fast) ------------
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

            existing = user_data.get("competence_ratings") or {}
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
                    idx = max(0, min(existing_lookup[norm_skill] - 1, len(level_labels) - 1))
                    matched_levels[skill] = level_labels[idx]
                else:
                    unmatched.append(skill)
            return flat_pairs, matched_levels, unmatched

        # --- Orchestrate: use as_completed so grading & reranking overlap ----------
        # Four I/O-bound tasks, two dependency chains:
        #   Chain A: extract_competences → grade_cv_match
        #   Chain B: embed+vector_search → rerank
        # as_completed dispatches the second step of each chain the moment its
        # dependency resolves, so both LLM calls (grade + rerank) run in parallel.
        with ThreadPoolExecutor(max_workers=4) as executor:
            competences_future = executor.submit(_phase1_extract_competences)
            rag_future = executor.submit(
                retrieve_similar_job_offers,
                data.job_text,
                collection,
                openai_client,
                user_id,
            )

            similar_documents = []
            top_docs = []
            grade_future = None
            rerank_future = None
            flat_pairs = []
            matched_levels = {}

            initial_futures = {competences_future: "competences", rag_future: "rag"}
            for done in as_completed(initial_futures):
                tag = initial_futures[done]
                if tag == "competences":
                    competences_by_cat = done.result()
                    logger.info("[EXTRACT] Competences extracted, submitting grading")
                    flat_pairs, matched_levels, unmatched = _process_competences(competences_by_cat)
                    grade_future = executor.submit(_phase2_grade, flat_pairs, unmatched)
                elif tag == "rag":
                    try:
                        raw_similar = done.result()
                        logger.info("[EXTRACT] RAG search returned %s raw results", len(raw_similar))
                        similar_documents = sanitize_search_results(raw_similar)
                        if raw_similar:
                            rerank_trace = Path("trace", "extraction.rerank")
                            rerank_trace.mkdir(parents=True, exist_ok=True)
                            rerank_future = executor.submit(
                                select_top_documents,
                                raw_similar,
                                data.job_text,
                                ai_client,
                                rerank_trace,
                            )
                    except Exception as rag_err:
                        logger.exception("[EXTRACT] RAG search failed: %s: %s", type(rag_err).__name__, rag_err)

            # Collect grading results
            levels = dict(matched_levels)
            if grade_future:
                llm_levels = grade_future.result()
                logger.info("[EXTRACT] CV grading complete")
                for skill in [s for s, _ in flat_pairs]:
                    if skill not in levels:
                        levels[skill] = llm_levels.get(skill, default_lvl)

            extraction = {
                "competences": {
                    skill: {"need": need, "level": levels.get(skill, default_lvl)}
                    for skill, need in flat_pairs
                },
                "requirements": [s for s, _ in flat_pairs],
            }
            logger.info("[EXTRACT] Extraction complete")

            # Collect reranking results
            all_scores = {}
            if rerank_future:
                try:
                    result = rerank_future.result()
                    top_docs = result["top_docs"]
                    all_scores = result.get("all_scores", {})
                    logger.info("[EXTRACT] LLM reranking selected %s top docs", len(top_docs))
                except Exception as rerank_err:
                    logger.warning("[EXTRACT] LLM reranking failed: %s", rerank_err)

            for doc in similar_documents:
                company = (doc.get("company_name_original") or doc.get("company_name") or "").strip()
                if company and company in all_scores:
                    doc["score"] = all_scores[company]

        if extraction:
            if "metadata" not in session:
                session["metadata"] = {}
            if "common" not in session["metadata"]:
                session["metadata"]["common"] = {}
            session["metadata"]["common"].update(extraction)
            session["job_text"] = data.job_text

        logger.info(
            "[EXTRACT] Returning %s similar_documents, %s top_docs",
            len(similar_documents),
            len(top_docs),
        )
        return with_user_monthly_cost({
            "status": "ok",
            "extraction": extraction,
            "similar_documents": similar_documents,
            "top_docs": top_docs,
            "session_id": session.session_key
        }, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-job/")
async def process_job(request: Request, data: ProcessJobRequest, session: Session = Depends(get_session)):
    try:
        instructions = session.get("style_instructions", "")
        if not instructions:
            instructions = get_style_instructions()
            
        kwargs = {
            "job_text": data.job_text,
            "cv_text": data.cv_text or session.get("cv_text", ""),
            "company_name": data.company_name,
            "model_vendor": ModelVendor(data.model_vendor) if data.model_vendor else None,
            "refine": data.refine,
            "fancy": data.fancy,
            "style_instructions": instructions,
            "out": Path("letters")
        }
        
        letters = write_cover_letter(**kwargs, logger=logger.info)
        
        # Persist logic (simplified)
        user = session.get('user')
        if user:
            # Upsert document logic if needed
            pass
            
        return with_user_monthly_cost({"status": "ok", "letters": letters}, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class TranslateRequest(BaseModel):
    text: str
    target_language: str
    source_language: Optional[str] = None

@router.post("/translate/")
async def translate(data: TranslateRequest, session: Session = Depends(get_session)):
    import httpx
    import os
    from letter_writer.cost_tracker import calculate_translation_cost, track_api_cost

    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_TRANSLATE_API_KEY not configured")

    if not data.text or not data.text.strip():
        return {"status": "ok", "translation": ""}

    params = {
        "q": data.text,
        "target": data.target_language,
        "format": "text",
        "key": api_key,
    }
    if data.source_language:
        params["source"] = data.source_language

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://translation.googleapis.com/language/translate/v2",
                data=params,
            )

        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.error("[TRANSLATE] Google API error %s: %s", resp.status_code, detail)
            raise HTTPException(status_code=502, detail=f"Google Translate API error: {resp.status_code}")

        body = resp.json()
        translated = body["data"]["translations"][0]["translatedText"]

        # Track cost
        user = session.get("user")
        user_id = user["id"] if user else "anonymous"
        char_count = len(data.text)
        cost = calculate_translation_cost(char_count)
        track_api_cost(
            user_id=user_id,
            phase="translate",
            vendor="google_translate",
            cost=cost,
            metadata={"character_count": char_count, "target_language": data.target_language},
        )

        return with_user_monthly_cost({"status": "ok", "translation": translated}, session)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[TRANSLATE] Error: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendors/")
async def list_vendors(session: Session = Depends(get_session)):
    vendors = [v.value for v in ModelVendor]
    active_vendors = set(vendors)

    session_selected = session.get("metadata", {}).get("common", {}).get("selected_vendors")
    if session_selected:
        active_vendors = set(session_selected)
    else:
        user = session.get("user")
        if user:
            user_data = get_user_data(user["id"], use_cache=True) or {}
            saved = get_models(user_data)
            if saved:
                active_vendors = set(saved)
                if "metadata" not in session:
                    session["metadata"] = {}
                if "common" not in session["metadata"]:
                    session["metadata"]["common"] = {}
                session["metadata"]["common"]["selected_vendors"] = saved

    return {
        "active": [v for v in vendors if v in active_vendors],
        "inactive": [v for v in vendors if v not in active_vendors]
    }

@router.get("/debug/in-flight-requests/")
async def debug_in_flight():
    return {"count": len(get_in_flight_requests()), "requests": get_in_flight_requests()}

@router.post("/debug/clear-in-flight-requests/")
async def debug_clear_in_flight():
    cleared = clear_in_flight_requests()
    return {"status": "ok", "cleared_count": cleared}
