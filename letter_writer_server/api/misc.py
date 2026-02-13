from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from letter_writer_server.core.session import Session, get_session
from letter_writer.client import get_client, ModelVendor
from letter_writer.generation import extract_job_metadata, MissingCVError, get_style_instructions
from letter_writer.service import write_cover_letter, refresh_repository
from letter_writer.firestore_store import get_collection, upsert_document, get_user_data
from letter_writer.retrieval import embed, retrieve_similar_job_offers, select_top_documents, sanitize_search_results
from letter_writer.personal_data_sections import get_models
from letter_writer.spam_prevention import get_in_flight_requests, clear_in_flight_requests
from openai import OpenAI

router = APIRouter()

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
        
        refresh_repository(**kwargs, logger=print)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/extract/")
async def extract_job(request: Request, data: ExtractRequest, session: Session = Depends(get_session)):
    user = session.get('user')
    # Load CV logic...
    cv_text = session.get('cv_text', "")
    if not cv_text and user:
        user_data = get_user_data(user['id'], use_cache=True)
        cv_revisions = user_data.get('cv_revisions', [])
        if cv_revisions:
            # Sort by created_at desc
            sorted_revs = sorted(cv_revisions, key=lambda x: x.get('created_at', ''), reverse=True)
            cv_text = sorted_revs[0].get('content', '')
            session['cv_text'] = cv_text
            
    if not cv_text:
        raise HTTPException(status_code=400, detail="CV text is missing")

    try:
        ai_client = get_client(ModelVendor.OPENAI)
        trace_dir = Path("trace", "extraction.openai")
        
        # Run extraction and RAG vector search in parallel
        # Both only need job_text; no dependency between them
        collection = get_collection()
        openai_client = OpenAI()
        
        print(f"[EXTRACT] Starting parallel: extraction + RAG search (job_text length={len(data.job_text)})")
        
        similar_documents = []
        top_docs = []
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            extract_future = executor.submit(
                extract_job_metadata,
                data.job_text,
                ai_client,
                trace_dir=trace_dir,
                cv_text=cv_text,
                scale_config=data.scale_config,
            )
            rag_future = executor.submit(
                retrieve_similar_job_offers,
                data.job_text,
                collection,
                openai_client,
            )
            
            # Wait for RAG first, then kick off LLM reranking in parallel with extraction
            try:
                raw_similar = rag_future.result()
                print(f"[EXTRACT] RAG search returned {len(raw_similar)} raw results")
                similar_documents = sanitize_search_results(raw_similar)
                print(f"[EXTRACT] After sanitization: {len(similar_documents)} documents")
                
                # LLM reranking — runs while extraction may still be in progress
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
                else:
                    rerank_future = None
            except Exception as rag_err:
                print(f"[EXTRACT] ERROR: RAG search failed: {type(rag_err).__name__}: {rag_err}")
                import traceback
                traceback.print_exc()
                rerank_future = None
            
            extraction = extract_future.result()
            print(f"[EXTRACT] Extraction complete")
            
            # Collect reranking result (non-blocking at this point, extraction already done)
            top_docs = []
            all_scores = {}
            if rerank_future:
                try:
                    result = rerank_future.result()
                    top_docs = result["top_docs"]
                    all_scores = result.get("all_scores", {})
                    print(f"[EXTRACT] LLM reranking selected {len(top_docs)} top docs, {len(all_scores)} scored")
                except Exception as rerank_err:
                    print(f"[EXTRACT] WARNING: LLM reranking failed: {rerank_err}")
            # Merge scores into similar_documents for display
            for doc in similar_documents:
                company = (doc.get("company_name_original") or doc.get("company_name") or "").strip()
                if company and company in all_scores:
                    doc["score"] = all_scores[company]
        
        if "metadata" not in session: session["metadata"] = {}
        if "common" not in session["metadata"]: session["metadata"]["common"] = {}
        session["metadata"]["common"].update(extraction)
        session["job_text"] = data.job_text
        
        print(f"[EXTRACT] Returning response with {len(similar_documents)} similar_documents, {len(top_docs)} top_docs")
        return {
            "status": "ok",
            "extraction": extraction,
            "similar_documents": similar_documents,
            "top_docs": top_docs,
            "session_id": session.session_key
        }
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
        
        letters = write_cover_letter(**kwargs, logger=print)
        
        # Persist logic (simplified)
        user = session.get('user')
        if user:
            # Upsert document logic if needed
            pass
            
        return {"status": "ok", "letters": letters}
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
            print(f"[TRANSLATE] Google API error {resp.status_code}: {detail}")
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

        return {"status": "ok", "translation": translated}

    except HTTPException:
        raise
    except Exception as e:
        print(f"[TRANSLATE] Error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendors/")
async def list_vendors(session: Session = Depends(get_session)):
    vendors = [v.value for v in ModelVendor]
    active_vendors = set(vendors)
    if session.get("metadata", {}).get("common", {}).get("selected_vendors"):
         active_vendors = set(session["metadata"]["common"]["selected_vendors"])
    
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
