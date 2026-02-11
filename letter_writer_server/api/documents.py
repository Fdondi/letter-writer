from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.firestore_store import (
    get_collection, 
    list_documents, 
    get_document, 
    upsert_document, 
    append_negatives
)
from letter_writer.retrieval import delete_documents, embed, retrieve_similar_job_offers, sanitize_search_results
from openai import OpenAI

router = APIRouter()

class DocumentRequest(BaseModel):
    company_name: Optional[str] = None
    job_text: Optional[str] = None
    ai_letters: Optional[List[Dict[str, Any]]] = None
    letter_text: Optional[str] = None
    vector: Optional[List[float]] = None

@router.get("/")
async def list_docs(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    params = request.query_params
    
    docs = list_documents(
        collection,
        user_id=user['id'],
        company_name=params.get("company_name"),
        role=params.get("role"),
        limit=int(params.get("limit", 50)),
        skip=int(params.get("skip", 0))
    )
    return {"documents": docs}

@router.post("/")
async def create_doc(request: Request, data: DocumentRequest, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not data.job_text:
        raise HTTPException(status_code=400, detail="job_text is required")
        
    collection = get_collection()
    openai_client = OpenAI()
    vector = embed(data.job_text, openai_client)
    
    doc_data = data.dict()
    doc_data["vector"] = vector
    
    try:
        document = upsert_document(collection, doc_data, allow_update=False, user_id=user['id'])
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
async def update_doc(document_id: str, data: DocumentRequest, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    collection = get_collection()
    doc_data = data.dict(exclude_unset=True)
    doc_data["id"] = document_id
    
    # Ensure vector exists: generate from job_text if not already stored
    if data.job_text and "vector" not in doc_data:
        existing = get_document(collection, document_id, user_id=user['id'])
        if not existing or not existing.get("vector"):
            openai_client = OpenAI()
            doc_data["vector"] = embed(data.job_text, openai_client)
    
    try:
        updated = upsert_document(collection, doc_data, allow_update=True, user_id=user['id'])
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
    except:
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
