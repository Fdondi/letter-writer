import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel
from pathlib import Path

from letter_writer_server.core.session import Session, get_session
from letter_writer.client import get_client, ModelVendor
from letter_writer.generation import (
    get_style_instructions,
)
from letter_writer.service import write_cover_letter, refresh_repository
from letter_writer.firestore_store import get_user_data
from letter_writer.personal_data_sections import get_models
from letter_writer_server.api.extract_pipeline import resolve_cv_for_extract, run_extract_pipeline
from letter_writer.spam_prevention import get_in_flight_requests, clear_in_flight_requests
from letter_writer_server.api.cost_utils import with_user_monthly_cost, check_spending_limits
from letter_writer_server.core.session import require_auth
from letter_writer.cost_tracker import track_api_cost

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


def _reset_client_counters(client) -> None:
    client.total_cost = 0.0
    client.total_input_tokens = 0
    client.total_output_tokens = 0
    if hasattr(client, "total_cached_tokens"):
        client.total_cached_tokens = 0
    if hasattr(client, "total_search_queries"):
        client.total_search_queries = 0


def _track_and_reset_client_cost(*, user_id: str, phase: str, vendor: str, client) -> None:
    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    if cost <= 0:
        _reset_client_counters(client)
        return
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    cached_tokens = int(getattr(client, "total_cached_tokens", 0) or 0)
    search_queries = int(getattr(client, "total_search_queries", 0) or 0)

    track_api_cost(
        user_id=user_id,
        phase=phase,
        vendor=vendor,
        cost=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        search_queries=search_queries if search_queries else None,
        cached_tokens=cached_tokens if cached_tokens else None,
    )
    _reset_client_counters(client)

@router.post("/refresh/")
async def refresh(request: Request, data: RefreshRequest, _user: dict = Depends(require_auth)):
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
async def extract_job(request: Request, data: ExtractRequest, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    """User-bound extraction: skills + CV match + similar past jobs, all in parallel."""
    try:
        ai_client = get_client(ModelVendor.OPENAI)
        _reset_client_counters(ai_client)
        cv_text, user_data, user_id = resolve_cv_for_extract(session)
        logger.info("[EXTRACT] Start: job_text length=%s", len(data.job_text))
        result = run_extract_pipeline(
            competence_source_text=data.job_text,
            similar_job_text=data.job_text,
            session=session,
            scale_cfg=data.scale_config,
            user_data=user_data,
            cv_text=cv_text,
            user_id=user_id,
            ai_client=ai_client,
        )
        _track_and_reset_client_cost(
            user_id=user_id, phase="extract", vendor=ModelVendor.OPENAI.value, client=ai_client
        )
        return with_user_monthly_cost({
            "status": "ok",
            "extraction": result["extraction"],
            "similar_documents": result["similar_documents"],
            "top_docs": result["top_docs"],
            "session_id": result["session_id"],
        }, session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-job/")
async def process_job(request: Request, data: ProcessJobRequest, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
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
    provider: Optional[str] = None
    target_level: Optional[str] = None
    language_instructions: Optional[str] = None

@router.post("/translate/")
async def translate(data: TranslateRequest, session: Session = Depends(get_session), _limit: None = Depends(check_spending_limits)):
    import httpx
    import os
    from letter_writer.cost_tracker import calculate_translation_cost, track_api_cost
    from letter_writer.firestore_store import get_user_data
    from letter_writer.generation import translate_with_llm
    from letter_writer.language_settings import get_translation_provider, resolve_language_entry

    if not data.text or not data.text.strip():
        return {"status": "ok", "translation": ""}

    user = session.get("user")
    user_id = user["id"] if user else "anonymous"
    user_data = get_user_data(user_id, use_cache=False) or {} if user else {}
    provider = (data.provider or get_translation_provider(user_data)).strip().lower()
    level_override = (data.target_level or "").strip() or None
    instructions_override = data.language_instructions if data.language_instructions is not None else None
    resolved = resolve_language_entry(
        user_data,
        data.target_language,
        level_override=level_override,
        instructions_override=instructions_override,
    )
    applied_level = (resolved or {}).get("level")

    if provider == "llm":
        try:
            translated = translate_with_llm(
                data.text,
                data.target_language,
                user_data,
                user_id,
                source_language=data.source_language,
                level_override=level_override,
                instructions_override=instructions_override,
            )
            return with_user_monthly_cost({
                "status": "ok",
                "translation": translated,
                "provider": "llm",
                "level_applied": applied_level,
            }, session)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("[TRANSLATE] LLM error: %s: %s", type(e).__name__, e)
            raise HTTPException(status_code=500, detail=str(e))

    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Translation service is not configured (GOOGLE_TRANSLATE_API_KEY missing; switch to LLM translation in Settings)")

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
        char_count = len(data.text)
        cost = calculate_translation_cost(char_count)
        track_api_cost(
            user_id=user_id,
            phase="translate",
            vendor="google_translate",
            cost=cost,
            metadata={"character_count": char_count, "target_language": data.target_language, "provider": "google"},
        )

        return with_user_monthly_cost({
            "status": "ok",
            "translation": translated,
            "provider": "google",
            "level_applied": None,
            "warning": (
                f"Google Translate ignores CEFR level ({applied_level or 'unset'}). "
                "Switch to LLM translation in Settings to honor language level."
            ) if applied_level else None,
        }, session)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[TRANSLATE] Error: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendors/")
async def list_vendors(session: Session = Depends(get_session)):
    from letter_writer.local_pricing import is_local_energy_pricing_configured

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
        "inactive": [v for v in vendors if v not in active_vendors],
        "local_pricing_configured": is_local_energy_pricing_configured(),
    }

@router.get("/debug/in-flight-requests/")
async def debug_in_flight(session: Session = Depends(get_session)):
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"count": len(get_in_flight_requests()), "requests": get_in_flight_requests()}

@router.post("/debug/clear-in-flight-requests/")
async def debug_clear_in_flight(session: Session = Depends(get_session)):
    if not session.get('user'):
        raise HTTPException(status_code=401, detail="Authentication required")
    cleared = clear_in_flight_requests()
    return {"status": "ok", "cleared_count": cleared}
