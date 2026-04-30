from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer_server.api.personal_data import _normalize_agent_feedback_context, _normalize_extra_info
from letter_writer.personal_data_sections import (
    merge_manual_agent_feedback_context_with_feedback_rows,
    merge_manual_extra_with_feedback_rows,
)
from letter_writer.session_store import (
    set_current_request,
    consume_pending_application_events,
    log_user_input_event,
)
from letter_writer.firestore_store import (
    get_collection,
    list_documents,
    get_document,
    upsert_document,
    append_negatives,
    save_feedback,
    get_personal_data_document,
    get_user_data,
    update_user_data_cache,
)
from letter_writer.retrieval import delete_documents, embed, retrieve_similar_job_offers, sanitize_search_results
from openai import OpenAI

router = APIRouter()


def _apply_feedback_extra_info_merge(user_id: str, raw: Any) -> None:
    """Merge validated feedback-only extra_info rows into personal_data (manual rows preserved)."""
    try:
        normalized = _normalize_extra_info(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    for row in normalized:
        if str(row.get("source") or "").lower() != "feedback":
            raise HTTPException(
                status_code=400,
                detail='each entry in feedback_extra_info must have source "feedback"',
            )
    now = datetime.now(timezone.utc)
    for row in normalized:
        row["updated_at"] = now
    user_data = get_user_data(user_id, use_cache=False) or {}
    combined = merge_manual_extra_with_feedback_rows(user_data, normalized)
    updates: Dict[str, Any] = {
        "extra_info": combined,
        "updated_at": now,
    }
    get_personal_data_document(user_id).set(updates, merge=True)
    update_user_data_cache(user_id, updates)


def _apply_feedback_agent_context_merge(user_id: str, raw: Any) -> None:
    """Merge validated feedback-only agent_feedback_context rows into personal_data (manual rows preserved)."""
    try:
        normalized = _normalize_agent_feedback_context(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    for row in normalized:
        if str(row.get("source") or "").lower() != "feedback":
            raise HTTPException(
                status_code=400,
                detail='each entry in feedback_agent_context must have source "feedback"',
            )
    now = datetime.now(timezone.utc)
    for row in normalized:
        row["updated_at"] = now
    user_data = get_user_data(user_id, use_cache=False) or {}
    combined = merge_manual_agent_feedback_context_with_feedback_rows(user_data, normalized)
    updates: Dict[str, Any] = {
        "agent_feedback_context": combined,
        "updated_at": now,
    }
    get_personal_data_document(user_id).set(updates, merge=True)
    update_user_data_cache(user_id, updates)


class DocumentRequest(BaseModel):
    company_name: Optional[str] = None
    role: Optional[str] = None
    location: Optional[str] = None
    language: Optional[str] = None
    salary: Optional[str] = None
    requirements: Optional[List[Any]] = None
    job_text: Optional[str] = None
    ai_letters: Optional[List[Dict[str, Any]]] = None
    letter_text: Optional[str] = None
    feedback_extra_info: Optional[List[Dict[str, Any]]] = None
    feedback_agent_context: Optional[List[Dict[str, Any]]] = None

@router.get("/")
async def list_docs(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    params = request.query_params
    
    try:
        limit = max(1, min(int(params.get("limit", 50)), 200))
        skip = max(0, int(params.get("skip", 0)))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="limit and skip must be integers")
    docs = list_documents(
        collection,
        user_id=user['id'],
        company_name=params.get("company_name"),
        role=params.get("role"),
        limit=limit,
        skip=skip,
    )
    return {"documents": docs}

@router.post("/")
async def create_doc(request: Request, data: DocumentRequest, session: Session = Depends(get_session)):
    set_current_request(request)
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not data.job_text:
        raise HTTPException(status_code=400, detail="job_text is required")
        
    collection = get_collection()
    openai_client = OpenAI()
    vector = embed(data.job_text, openai_client)
    
    doc_data = data.dict()
    log_user_input_event("documents.create", doc_data)
    pending_events = consume_pending_application_events()
    if pending_events:
        doc_data["application_event_log"] = pending_events
    doc_data["vector"] = vector
    
    try:
        document = upsert_document(collection, doc_data, allow_update=False, user_id=user['id'])
        if data.ai_letters:
            save_feedback(
                user_id=user['id'],
                document_id=document["id"],
                letter_text=data.letter_text or "",
                ai_letters=data.ai_letters,
            )
        if data.feedback_extra_info is not None:
            _apply_feedback_extra_info_merge(user["id"], data.feedback_extra_info)
        if data.feedback_agent_context is not None:
            _apply_feedback_agent_context_merge(user["id"], data.feedback_agent_context)
        return {"document": document}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

class SimilarRequest(BaseModel):
    job_text: str

@router.post("/similar/")
async def get_similar_docs(data: SimilarRequest, session: Session = Depends(get_session)):
    """Return similar previous job offers from the documents collection via RAG vector search."""
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not data.job_text or not data.job_text.strip():
        raise HTTPException(status_code=400, detail="job_text is required")
    
    collection = get_collection()
    try:
        openai_client = OpenAI()
        raw_results = retrieve_similar_job_offers(data.job_text, collection, openai_client)
        return {"documents": sanitize_search_results(raw_results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{document_id}/")
async def get_doc(document_id: str, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    try:
        doc = get_document(collection, document_id, user_id=user['id'])
        if not doc:
            raise HTTPException(status_code=404, detail="Not found")
        return {"document": doc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{document_id}/")
async def update_doc(document_id: str, data: DocumentRequest, request: Request, session: Session = Depends(get_session)):
    set_current_request(request)
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    doc_data = data.dict(exclude_unset=True)
    log_user_input_event("documents.update", {"document_id": document_id, "payload": doc_data})
    pending_events = consume_pending_application_events()
    if pending_events:
        doc_data["application_event_log"] = pending_events
    doc_data["id"] = document_id
    
    # Keep vector server-owned:
    # - never trust/store client-provided vectors
    # - recompute when job_text changes
    # - backfill if vector is missing
    existing = get_document(collection, document_id, user_id=user['id'])
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    existing_raw_snapshot = collection.document(document_id).get()
    existing_raw = existing_raw_snapshot.to_dict() if existing_raw_snapshot.exists else {}
    if data.job_text:
        existing_job_text = (existing.get("job_text") or "").strip()
        new_job_text = data.job_text.strip()
        needs_reembed = (new_job_text != existing_job_text) or ("vector" not in existing_raw)
        if needs_reembed:
            openai_client = OpenAI()
            doc_data["vector"] = embed(new_job_text, openai_client)
    
    try:
        updated = upsert_document(collection, doc_data, allow_update=True, user_id=user['id'])
        if data.ai_letters:
            save_feedback(
                user_id=user['id'],
                document_id=document_id,
                letter_text=data.letter_text or "",
                ai_letters=data.ai_letters,
            )
        if data.feedback_extra_info is not None:
            _apply_feedback_extra_info_merge(user["id"], data.feedback_extra_info)
        if data.feedback_agent_context is not None:
            _apply_feedback_agent_context_merge(user["id"], data.feedback_agent_context)
        return {"document": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{document_id}/")
async def delete_doc(document_id: str, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    # Check ownership
    try:
        doc = get_document(collection, document_id, user_id=user['id'])
        if not doc:
            raise HTTPException(status_code=404, detail="Not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
        
    delete_documents(collection, [document_id])
    return {"status": "deleted"}

@router.post("/{document_id}/negatives/")
async def add_negatives(document_id: str, request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    data = await request.json()
    negatives = data.get("negatives", [])
    
    collection = get_collection()
    try:
        updated = append_negatives(collection, document_id, negatives, user_id=user['id'])
        return {"document": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{document_id}/reembed/")
async def reembed_doc(document_id: str, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    doc = get_document(collection, document_id, user_id=user['id'])
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
        
    if not doc.get("job_text"):
        raise HTTPException(status_code=400, detail="Missing job_text")
        
    openai_client = OpenAI()
    vector = embed(doc["job_text"], openai_client)
    
    collection.document(document_id).update({"vector": vector})
    return {"status": "ok"}
