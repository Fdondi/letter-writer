from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional, TYPE_CHECKING
from threading import Lock, local

from google.cloud import firestore

from .firestore_store import get_firestore_client
from .clients.base import ModelVendor

# Thread-local storage for Django request (for cookie-based sessions)
_thread_local = local()

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
        "style_instructions": session.style_instructions,
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
        style_instructions=data.get("style_instructions", ""),
        search_result=data.get("search_result", []),  # Already List[dict]
        vendors={},  # Will be overwritten by session_vendors data in load_session()
        metadata=data.get("metadata", {}),
        vendors_list=[ModelVendor(v) for v in data.get("vendors_list", [])],
    )


def save_session(session, collection=None) -> None:
    """Save a session to Django sessions.
    
    REQUIRES request context - all session data is stored in Django sessions (in-memory).
    All restore must be from client data if server restarts.
    """
    request = _get_current_request()
    if request is None:
        raise RuntimeError(
            "save_session called without request context. "
            "Session operations require a Django request. "
            "If server restarted, restore from client-side data."
        )
    
    from letter_writer_server.api.session_helpers import (
        save_session_common_data,
        save_vendor_data,
    )
    
    # Save common data
    # NOTE: cv_text is never saved to Django session - it's loaded from Firestore when needed
    save_session_common_data(
        request=request,
        job_text=session.job_text,
        style_instructions=session.style_instructions,
        metadata=session.metadata,
        search_result=session.search_result,
    )
    
    # Save vendor data
    for vendor_name, vendor_state in session.vendors.items():
        save_vendor_data(request, vendor_name, vendor_state)
    
    # Update cache (for compatibility)
    with CACHE_LOCK:
        SESSION_CACHE[session.session_id] = session


def save_session_common_data(session_id: str, job_text: str, cv_text: str,
                             metadata: dict, search_result: list = None, style_instructions: str = "", collection=None) -> None:
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
                "style_instructions": style_instructions,
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
                "style_instructions": style_instructions,
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
        "style_instructions": doc_dict.get("style_instructions", ""),
        "search_result": doc_dict.get("search_result", []),  # Already List[dict]
        "metadata": doc_dict.get("metadata", {}),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _get_current_request():
    """Get current Django request from thread-local storage."""
    return getattr(_thread_local, 'request', None)


def set_current_request(request):
    """Set current Django request in thread-local storage."""
    _thread_local.request = request


def save_vendor_data(session_id: str, vendor: str, vendor_state, collection=None) -> None:
    """Atomically save vendor-specific data to Django sessions.
    
    NO LONGER USES FIRESTORE - all session data is stored in Django sessions (in-memory).
    Each vendor writes to independent keys (vendors[vendor_name]), allowing parallel writes.
    """
    # Get Django request from thread-local storage
    request = _get_current_request()
    if request is None:
        raise RuntimeError(
            "save_vendor_data called without request context. "
            "Ensure set_current_request() is called before using phased_service functions."
        )
    
    # Use Django sessions (no Firestore fallback)
    from letter_writer_server.api.session_helpers import save_vendor_data as django_save_vendor_data
    django_save_vendor_data(request, vendor, vendor_state)


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
    """Load all vendor data for a session from Django sessions.
    
    REQUIRES request context - all vendor data is stored in Django sessions (in-memory).
    All restore must be from client data if server restarts.
    """
    request = _get_current_request()
    if request is None:
        raise RuntimeError(
            "load_all_vendor_data called without request context. "
            "Session operations require a Django request. "
            "If server restarted, restore from client-side data."
        )
    
    from letter_writer_server.api.session_helpers import load_all_vendor_data as django_load_all_vendor_data
    
    # Verify session_id matches
    if request.session.session_key != session_id:
        raise ValueError(
            f"Session ID mismatch: requested {session_id}, got {request.session.session_key}. "
            "If server restarted, restore from client-side data."
        )
    
    return django_load_all_vendor_data(request)


def load_session(session_id: str, collection=None, force_reload: bool = False):
    """Load a session from Django sessions.
    
    REQUIRES request context - all session data is stored in Django sessions (in-memory).
    All restore must be from client data if server restarts.
    
    Args:
        session_id: The session ID to load
        collection: Ignored (kept for backward compatibility)
        force_reload: Ignored (Django sessions are always fresh)
    """
    request = _get_current_request()
    if request is None:
        raise RuntimeError(
            "load_session called without request context. "
            "Session operations require a Django request. "
            "If server restarted, restore from client-side data."
        )
    
    from letter_writer_server.api.session_helpers import (
        load_session_common_data,
        load_all_vendor_data as django_load_all_vendor_data,
    )
    
    # Verify session_id matches
    if request.session.session_key != session_id:
        raise ValueError(
            f"Session ID mismatch: requested {session_id}, got {request.session.session_key}. "
            "If server restarted, restore from client-side data."
        )
    
    # Load common data from Django session
    common_data = load_session_common_data(request)
    if common_data is None:
        return None
    
    # Load vendor data from Django session
    vendors_data = django_load_all_vendor_data(request)
    
    # Convert Django session format to SessionState object
    from .phased_service import SessionState, VendorPhaseState
    
    # Convert vendor data dict to VendorPhaseState objects
    vendors = {}
    for vendor_name, vendor_dict in vendors_data.items():
        vendors[vendor_name] = VendorPhaseState(
            top_docs=vendor_dict.get("top_docs", []),
            company_report=vendor_dict.get("company_report"),
            draft_letter=vendor_dict.get("draft_letter"),
            final_letter=vendor_dict.get("final_letter"),
            feedback=vendor_dict.get("feedback", {}),
            cost=vendor_dict.get("cost", 0.0),
        )
    
    # Create SessionState object
    session = SessionState(
        session_id=session_id,
        job_text=common_data.get("job_text", ""),
        cv_text=common_data.get("cv_text", ""),
        style_instructions=common_data.get("style_instructions", ""),
        search_result=common_data.get("search_result", []),
        metadata=common_data.get("metadata", {}),
        vendors=vendors,
    )
    
    # Update cache (for compatibility)
    with CACHE_LOCK:
        SESSION_CACHE[session_id] = session
    
    return session


def get_session(session_id: str, collection=None):
    """Get a session from Django sessions. Returns None if not found.
    
    REQUIRES request context - all session data is stored in Django sessions (in-memory).
    All restore must be from client data if server restarts.
    """
    return load_session(session_id, collection)


def delete_session(session_id: str, collection=None) -> None:
    """Delete a session from Django sessions.
    
    REQUIRES request context - all session data is stored in Django sessions (in-memory).
    """
    request = _get_current_request()
    if request is None:
        raise RuntimeError(
            "delete_session called without request context. "
            "Session operations require a Django request."
        )
    
    # Clear the Django session
    from letter_writer_server.api.session_helpers import clear_session_data
    clear_session_data(request)
    
    # Remove from cache
    with CACHE_LOCK:
        SESSION_CACHE.pop(session_id, None)


def clear_cache() -> None:
    """Clear the in-memory cache (useful for testing or memory management)."""
    with CACHE_LOCK:
        SESSION_CACHE.clear()
