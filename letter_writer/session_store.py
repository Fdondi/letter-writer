from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional, TYPE_CHECKING
from threading import Lock

from google.cloud import firestore

from .firestore_store import get_firestore_client
from .clients.base import ModelVendor

if TYPE_CHECKING:
    from .phased_service import SessionState, VendorPhaseState
else:
    # Import at runtime to avoid circular dependency
    SessionState = None
    VendorPhaseState = None


# In-memory cache
SESSION_CACHE: Dict[str, any] = {}
CACHE_LOCK = Lock()

# Lock for session creation (only needed when creating new sessions)
SESSION_CREATE_LOCK = Lock()

# TTL: 30 days (1 month)
SESSION_TTL_DAYS = 30


def _get_sessions_collection():
    """Get Firestore collection for sessions."""
    client = get_firestore_client()
    return client.collection("sessions")


def _get_session_vendors_collection():
    """Get Firestore collection for session vendors."""
    client = get_firestore_client()
    return client.collection("session_vendors")


def _serialize_vendor_state(state) -> dict:
    """Serialize VendorPhaseState to a dict."""
    return {
        "top_docs": state.top_docs,
        "company_report": state.company_report,
        "draft_letter": state.draft_letter,
        "final_letter": state.final_letter,
        "feedback": state.feedback,
        "cost": state.cost,
    }


def _deserialize_vendor_state(data: dict):
    """Deserialize a dict to VendorPhaseState."""
    # Import here to avoid circular dependency
    from .phased_service import VendorPhaseState
    
    return VendorPhaseState(
        top_docs=data.get("top_docs", []),
        company_report=data.get("company_report"),
        draft_letter=data.get("draft_letter"),
        final_letter=data.get("final_letter"),
        feedback=data.get("feedback", {}),
        cost=float(data.get("cost", 0.0)),
    )


def _serialize_session(session) -> dict:
    """Serialize SessionState to a dict for Firestore storage.
    
    Note: vendor data is NOT stored here - it's stored in the session_vendors
    collection for lock-free parallel processing. Use save_vendor_data() to save vendor state.
    """
    # search_result is now List[dict], no need for ScoredPoint serialization
    return {
        "session_id": session.session_id,
        "job_text": session.job_text,
        "cv_text": session.cv_text,
        "search_result": session.search_result,  # Already List[dict]
        # vendors NOT stored here - stored in session_vendors collection
        "metadata": session.metadata,
        "vendors_list": [v.value for v in session.vendors_list],
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        # TTL field for automatic expiration
        "expire_at": datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS),
    }


def _deserialize_session(data: dict):
    """Deserialize a dict from Firestore to SessionState.
    
    Note: vendor data is loaded separately from session_vendors collection in load_session().
    """
    # Import here to avoid circular dependency
    from .phased_service import SessionState
    
    # search_result is already List[dict] (no ScoredPoint deserialization needed)
    return SessionState(
        session_id=data["session_id"],
        job_text=data["job_text"],
        cv_text=data["cv_text"],
        search_result=data.get("search_result", []),  # Already List[dict]
        vendors={},  # Will be overwritten by session_vendors data in load_session()
        metadata=data.get("metadata", {}),
        vendors_list=[ModelVendor(v) for v in data.get("vendors_list", [])],
    )


def save_session(session, collection=None) -> None:
    """Save a session to Firestore and update the in-memory cache."""
    if collection is None:
        collection = _get_sessions_collection()
    
    doc = _serialize_session(session)
    now = datetime.utcnow()
    doc["updated_at"] = now
    doc["expire_at"] = now + timedelta(days=SESSION_TTL_DAYS)
    
    # Get existing document to preserve created_at
    doc_ref = collection.document(session.session_id)
    existing_doc = doc_ref.get()
    
    if existing_doc.exists:
        existing_data = existing_doc.to_dict()
        # Preserve existing created_at
        doc["created_at"] = existing_data.get("created_at", now)
    else:
        doc["created_at"] = now
    
    # Upsert to Firestore
    doc_ref.set(doc, merge=True)
    
    # Update in-memory cache
    with CACHE_LOCK:
        SESSION_CACHE[session.session_id] = session


def save_session_common_data(session_id: str, job_text: str, cv_text: str,
                             metadata: dict, search_result: list = None, collection=None) -> None:
    """Save or update common session data. Called by extraction phase or start phased flow.
    
    This is the ONLY place that writes common session data. Uses lock for session creation.
    """
    if collection is None:
        collection = _get_sessions_collection()
    
    now = datetime.utcnow()
    
    # Use lock only for session creation to prevent duplicate sessions
    with SESSION_CREATE_LOCK:
        doc_ref = collection.document(session_id)
        existing_doc = doc_ref.get()
        
        if not existing_doc.exists:
            # Create new session
            doc_ref.set({
                "session_id": session_id,
                "job_text": job_text,
                "cv_text": cv_text,
                "search_result": search_result or [],  # Already List[dict]
                "metadata": metadata,
                "created_at": now,
                "updated_at": now,
                "expire_at": now + timedelta(days=SESSION_TTL_DAYS),
            })
        else:
            # Update existing session - merge metadata, update other fields
            existing_data = existing_doc.to_dict()
            update_data = {
                "job_text": job_text,
                "cv_text": cv_text,
                "updated_at": now,
                "expire_at": now + timedelta(days=SESSION_TTL_DAYS),
            }
            
            # Merge metadata (don't overwrite existing, merge at field level)
            merged_metadata = existing_data.get("metadata", {}).copy()
            merged_metadata.update(metadata)
            update_data["metadata"] = merged_metadata
            
            # Update search_result if provided
            if search_result is not None:
                update_data["search_result"] = search_result
            
            doc_ref.update(update_data)


def load_session_common_data(session_id: str, collection=None):
    """Load common session data (job_text, cv_text, metadata, search_result, etc.)."""
    if collection is None:
        collection = _get_sessions_collection()
    
    doc_ref = collection.document(session_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return None
    
    doc_dict = doc.to_dict()
    
    # Convert Firestore Timestamps to datetime if needed
    created_at = doc_dict.get("created_at")
    updated_at = doc_dict.get("updated_at")
    if hasattr(created_at, 'isoformat'):
        created_at = created_at
    if hasattr(updated_at, 'isoformat'):
        updated_at = updated_at
    
    return {
        "session_id": doc_dict["session_id"],
        "job_text": doc_dict.get("job_text", ""),
        "cv_text": doc_dict.get("cv_text", ""),
        "search_result": doc_dict.get("search_result", []),  # Already List[dict]
        "metadata": doc_dict.get("metadata", {}),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def save_vendor_data(session_id: str, vendor: str, vendor_state, collection=None) -> None:
    """Atomically save vendor-specific data to separate collection.
    
    Each vendor has their own document keyed by (session_id, vendor).
    This is completely lock-free - vendors can work in parallel.
    """
    if collection is None:
        collection = _get_session_vendors_collection()
    
    # Import here to avoid circular dependency
    vendor_data = _serialize_vendor_state(vendor_state)
    
    now = datetime.utcnow()
    
    # Create document ID: session_id + vendor (compound key)
    doc_id = f"{session_id}_{vendor}"
    doc_ref = collection.document(doc_id)
    
    # Upsert vendor-specific data - completely independent from other vendors
    update_data = {
        "session_id": session_id,
        "vendor": vendor,
        **vendor_data,  # Unpack vendor state data
        "updated_at": now,
        "expire_at": now + timedelta(days=SESSION_TTL_DAYS),
    }
    
    # Check if document exists to preserve created_at
    existing_doc = doc_ref.get()
    if existing_doc.exists:
        existing_data = existing_doc.to_dict()
        update_data["created_at"] = existing_data.get("created_at", now)
    else:
        update_data["created_at"] = now
    
    doc_ref.set(update_data, merge=True)


def load_vendor_data(session_id: str, vendor: str, collection=None):
    """Load vendor-specific data."""
    if collection is None:
        collection = _get_session_vendors_collection()
    
    doc_id = f"{session_id}_{vendor}"
    doc_ref = collection.document(doc_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return None
    
    return _deserialize_vendor_state(doc.to_dict())


def load_all_vendor_data(session_id: str, collection=None):
    """Load all vendor data for a session."""
    if collection is None:
        collection = _get_session_vendors_collection()
    
    # Query all vendor documents for this session
    query = collection.where("session_id", "==", session_id).stream()
    
    result = {}
    for doc in query:
        doc_dict = doc.to_dict()
        vendor = doc_dict["vendor"]
        result[vendor] = _deserialize_vendor_state(doc_dict)
    
    return result


def load_session(session_id: str, collection=None, force_reload: bool = False):
    """Load a session from Firestore if not in cache. Returns None if not found.
    
    Also loads vendor data from the session_vendors collection.
    
    Args:
        session_id: The session ID to load
        collection: Optional Firestore collection reference
        force_reload: If True, bypass cache and reload from Firestore
    """
    # Check cache first (unless forcing reload)
    if not force_reload:
        with CACHE_LOCK:
            if session_id in SESSION_CACHE:
                return SESSION_CACHE[session_id]
    
    # Load from Firestore
    if collection is None:
        collection = _get_sessions_collection()
    
    doc_ref = collection.document(session_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return None
    
    try:
        doc_dict = doc.to_dict()
        session = _deserialize_session(doc_dict)
        
        # Load vendor data from separate collection
        vendor_collection = _get_session_vendors_collection()
        vendor_data = load_all_vendor_data(session_id, collection=vendor_collection)
        if vendor_data:
            # session_vendors is the source of truth for vendor-specific data
            # Update session.vendors with data from session_vendors collection
            session.vendors.update(vendor_data)
        
        # Update cache
        with CACHE_LOCK:
            SESSION_CACHE[session_id] = session
        return session
    except Exception as e:
        # If deserialization fails, raise a more descriptive error
        import traceback
        error_msg = f"Failed to deserialize session {session_id}: {e}"
        print(f"Error deserializing session {session_id}: {e}")
        traceback.print_exc()
        raise ValueError(error_msg) from e


def get_session(session_id: str, collection=None):
    """Get a session from cache or Firestore. Returns None if not found."""
    return load_session(session_id, collection)


def delete_session(session_id: str, collection=None) -> None:
    """Delete a session from Firestore and cache."""
    if collection is None:
        collection = _get_sessions_collection()
    
    # Delete session document
    doc_ref = collection.document(session_id)
    doc_ref.delete()
    
    # Delete all vendor documents for this session
    vendor_collection = _get_session_vendors_collection()
    vendor_query = vendor_collection.where("session_id", "==", session_id).stream()
    
    batch = get_firestore_client().batch()
    batch_count = 0
    max_batch_size = 500
    
    for vendor_doc in vendor_query:
        batch.delete(vendor_collection.document(vendor_doc.id))
        batch_count += 1
        if batch_count >= max_batch_size:
            batch.commit()
            batch = get_firestore_client().batch()
            batch_count = 0
    
    if batch_count > 0:
        batch.commit()
    
    # Remove from cache
    with CACHE_LOCK:
        SESSION_CACHE.pop(session_id, None)


def clear_cache() -> None:
    """Clear the in-memory cache (useful for testing or memory management)."""
    with CACHE_LOCK:
        SESSION_CACHE.clear()
