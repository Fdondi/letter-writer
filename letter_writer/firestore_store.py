from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import uuid4

from google.cloud import firestore

from .config import env_default


def get_firestore_client() -> firestore.Client:
    """Return a Firestore client using env defaults."""
    project_id = env_default("GOOGLE_CLOUD_PROJECT") or env_default("FIRESTORE_PROJECT_ID")
    database_id = env_default("FIRESTORE_DATABASE")
    # Firestore client will use Application Default Credentials
    # Set GOOGLE_APPLICATION_CREDENTIALS env var or use gcloud auth
    return firestore.Client(project=project_id, database=database_id)


def get_collection():
    """Return the Firestore collection reference."""
    client = get_firestore_client()
    collection_name = env_default("FIRESTORE_COLLECTION", "documents")
    return client.collection(collection_name)


def _prepare_ai_letters(ai_letters: Optional[List[dict]]) -> List[dict]:
    """Normalize AI/negative letters for storage."""
    now = datetime.utcnow()
    prepared: List[dict] = []
    for letter in ai_letters or []:
        if not isinstance(letter, dict):
            continue
        prepared.append(
            {
                "id": letter.get("id") or str(uuid4()),
                "vendor": letter.get("vendor"),
                "model": letter.get("model"),
                "text": (letter.get("text") or "").strip(),
                "cost": letter.get("cost"),
                "created_at": letter.get("created_at") or now,
            }
        )
    return prepared


def serialize_document(doc_dict: dict, doc_id: str) -> dict:
    """Serialize a Firestore document to dict format."""
    if not doc_dict:
        return {}
    result = dict(doc_dict)
    result["id"] = doc_id
    result["ai_letters"] = doc_dict.get("ai_letters") or []
    # Convert Firestore Timestamps to ISO format strings
    for ts_field in ("created_at", "updated_at"):
        if ts_field in doc_dict:
            ts = doc_dict[ts_field]
            if hasattr(ts, "isoformat"):
                result[ts_field] = ts.isoformat()
            elif isinstance(ts, datetime):
                result[ts_field] = ts.isoformat()
    return result


def upsert_document(collection, data: dict, *, allow_update: bool = True) -> dict:
    """Insert or update a document. Returns the stored document.
    
    Args:
        collection: Firestore collection reference
        data: Document data dict
        allow_update: If True, update existing document; if False, only insert
    """
    now = datetime.utcnow()
    doc_id = data.get("id") or data.get("document_id") or data.get("_id") or str(uuid4())
    company_name_raw = data.get("company_name") or data.get("company")
    # Normalize company_name by stripping whitespace and lowercasing
    company_name = company_name_raw.strip().lower() if company_name_raw else None
    
    role = data.get("role")
    
    ai_letters = _prepare_ai_letters(data.get("ai_letters"))
    requirements = data.get("requirements")
    if isinstance(requirements, list):
        requirements_value = requirements
    elif requirements:
        requirements_value = [requirements]
    else:
        requirements_value = []

    doc_ref = collection.document(doc_id)
    
    if allow_update:
        existing_doc = doc_ref.get()
        existing_data = existing_doc.to_dict() if existing_doc.exists else None
        
        if existing_data:
            # Update existing document
            version = int(existing_data.get("version", 1))
            # Increment version if letter_text or job_text changed
            if (data.get("letter_text", "").strip() != existing_data.get("letter_text", "").strip() or
                data.get("job_text", "").strip() != existing_data.get("job_text", "").strip()):
                version += 1
        else:
            version = 1
    else:
        existing_data = None
        version = 1
    
    base = {
        "company_name": company_name,
        "company_name_original": data.get("company_name") or data.get("company"),  # Store original for display
        "role": role,
        "location": data.get("location"),
        "language": data.get("language"),
        "salary": data.get("salary"),
        "requirements": requirements_value,
        "date_applied": data.get("date_applied"),
        "status": data.get("status"),
        "vendor": data.get("vendor"),
        "model": data.get("model"),
        "job_text": (data.get("job_text") or "").strip(),
        "letter_text": (data.get("letter_text") or "").strip(),
        "negative_letter_text": (data.get("negative_letter_text") or "").strip() if data.get("negative_letter_text") else None,
        "blocks": data.get("blocks") or [],
        "ai_letters": ai_letters,
        "tags": data.get("tags") or [],
        "notes": data.get("notes"),
        "version": version,
        "updated_at": now,
    }
    
    # Set created_at only on insert
    if not existing_data:
        base["created_at"] = data.get("created_at") or now
    else:
        # Preserve existing created_at
        base["created_at"] = existing_data.get("created_at", now)
    
    # Store vector if provided (for vector search)
    if "vector" in data:
        base["vector"] = data["vector"]
    
    # Upsert document
    doc_ref.set(base, merge=allow_update)
    
    # Get the stored document
    stored_doc = doc_ref.get()
    stored_dict = stored_doc.to_dict() if stored_doc.exists else {}
    
    return serialize_document(stored_dict, doc_id)


def get_document(collection, doc_id: str) -> dict | None:
    """Get a document by ID."""
    doc_ref = collection.document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        return None
    return serialize_document(doc.to_dict(), doc_id)


def list_documents(
    collection,
    *,
    company_name: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    limit: int = 50,
    skip: int = 0,
) -> List[dict]:
    """List documents with optional filters."""
    query = collection
    
    # Apply filters - note: Firestore doesn't support regex, so we use exact match or prefix
    # Store company_name lowercase for consistent queries
    if company_name:
        # Use prefix matching with lowercase
        company_lower = company_name.lower().strip()
        query = query.where("company_name", ">=", company_lower)
        query = query.where("company_name", "<=", company_lower + "\uf8ff")
    
    if role:
        # For role, we can do exact match or prefix (no regex support)
        # Assuming users will type exact role names
        role_normalized = role.lower().strip()
        query = query.where("role", ">=", role_normalized)
        query = query.where("role", "<=", role_normalized + "\uf8ff")
    
    if status:
        query = query.where("status", "==", status)
    
    if vendor:
        query = query.where("vendor", "==", vendor)
    
    if model:
        query = query.where("model", "==", model)
    
    if tags:
        # Firestore supports array-contains for each tag (need to use array-contains-any or multiple filters)
        # For array-contains-all, we need to chain array-contains filters
        tags_list = list(tags)
        if tags_list:
            # Firestore doesn't have array-contains-all, so filter client-side or use multiple array-contains
            # For now, use array-contains-any which requires at least one tag
            query = query.where("tags", "array-contains-any", tags_list)
    
    # Order by updated_at descending
    query = query.order_by("updated_at", direction=firestore.Query.DESCENDING)
    
    # Apply pagination
    if skip > 0:
        query = query.offset(skip)
    query = query.limit(limit)
    
    # Execute query
    docs = query.stream()
    result = []
    for doc in docs:
        result.append(serialize_document(doc.to_dict(), doc.id))
    
    return result


def append_negatives(collection, doc_id: str, negatives: List[dict]) -> dict | None:
    """Append negatives to ai_letters array."""
    if not negatives:
        return get_document(collection, doc_id)
    
    now = datetime.utcnow()
    prepared = _prepare_ai_letters(negatives)
    
    doc_ref = collection.document(doc_id)
    
    # Get current document and append to array
    current_doc = doc_ref.get()
    if not current_doc.exists:
        return None
    
    current_data = current_doc.to_dict()
    current_ai_letters = current_data.get("ai_letters", [])
    updated_ai_letters = current_ai_letters + prepared
    
    # Update document
    doc_ref.update({
        "ai_letters": updated_ai_letters,
        "updated_at": now,
    })
    
    return get_document(collection, doc_id)


def documents_by_ids(collection, ids: List[str]) -> List[dict]:
    """Get multiple documents by IDs."""
    if not ids:
        return []
    
    # Firestore batch get
    doc_refs = [collection.document(doc_id) for doc_id in ids]
    docs = get_firestore_client().get_all(doc_refs)
    
    result = []
    for doc in docs:
        if doc.exists:
            result.append(serialize_document(doc.to_dict(), doc.id))
    
    return result
