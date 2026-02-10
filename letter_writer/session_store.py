from __future__ import annotations
from typing import Dict, Optional, TYPE_CHECKING, Any, List
from threading import local, Lock
from datetime import datetime

# Thread-local storage for Request (FastAPI)
_thread_local = local()

# In-memory cache (kept for compatibility with existing code structure, though session middleware handles caching)
SESSION_CACHE: Dict[str, Any] = {}
CACHE_LOCK = Lock()

if TYPE_CHECKING:
    from fastapi import Request
    from letter_writer_server.core.session import Session
    from .phased_service import SessionState, VendorPhaseState

def set_current_request(request: Request):
    """Set current FastAPI request in thread-local storage."""
    _thread_local.request = request

def _get_current_request() -> Optional[Request]:
    """Get current FastAPI request from thread-local storage."""
    return getattr(_thread_local, 'request', None)

def _get_session() -> Optional[Session]:
    """Get the custom Session object from the current request."""
    request = _get_current_request()
    if request and hasattr(request.state, 'session'):
        return request.state.session
    return None

def check_session_exists(session_id: str) -> bool:
    """Check if a session exists."""
    session = _get_session()
    # In the new system, if we have a session object, it exists.
    # We might want to check if it has any data to be sure it's a valid session
    return bool(session and (session.get('job_text') or session.get('vendors')))

def save_session_common_data(session_id: str, job_text: str, cv_text: str,
                             metadata: dict, search_result: list = None, style_instructions: str = "", collection=None) -> None:
    session = _get_session()
    if not session:
        return 
    
    session['job_text'] = job_text
    session['cv_text'] = cv_text
    session['style_instructions'] = style_instructions
    if search_result is not None:
        session['search_result'] = search_result
    
    # Merge metadata
    current_meta = session.get('metadata', {})
    if isinstance(current_meta, dict):
        # We need to be careful not to overwrite existing keys if we want merge behavior
        # But here we are passed 'metadata' which might be the full metadata or update
        # The original implementation merged at field level
        merged = current_meta.copy()
        merged.update(metadata)
        session['metadata'] = merged
    else:
        session['metadata'] = metadata
        
    session['updated_at'] = datetime.utcnow().isoformat()
    if 'created_at' not in session:
        session['created_at'] = datetime.utcnow().isoformat()

def load_session_common_data(session_id: str, collection=None):
    session = _get_session()
    if not session:
        return None
    
    # If session is empty but we have a session object (new session), return defaults
    return {
        "session_id": session_id,
        "job_text": session.get("job_text", ""),
        "cv_text": session.get("cv_text", ""),
        "style_instructions": session.get("style_instructions", ""),
        "search_result": session.get("search_result", []),
        "metadata": session.get("metadata", {}),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }

def _serialize_vendor_state(state) -> dict:
    """Serialize VendorPhaseState to a dict."""
    return {
        "top_docs": state.top_docs,
        "company_report": state.company_report,
        "draft_letter": state.draft_letter,
        "final_letter": state.final_letter,
        "feedback": state.feedback,
        "cost": state.cost,
        # We should also serialize phase_costs if present, but for now basic fields
    }

def _deserialize_vendor_state(data: dict):
    """Deserialize a dict to VendorPhaseState."""
    from .phased_service import VendorPhaseState
    
    # Handle both old and new format if needed
    return VendorPhaseState(
        top_docs=data.get("top_docs", []),
        company_report=data.get("company_report"),
        draft_letter=data.get("draft_letter"),
        final_letter=data.get("final_letter"),
        feedback=data.get("feedback", {}),
        cost=float(data.get("cost", 0.0)),
    )

def save_vendor_data(session_id: str, vendor: str, vendor_state, collection=None) -> None:
    session = _get_session()
    if not session:
        return

    state_dict = _serialize_vendor_state(vendor_state)
    
    vendors = session.get('vendors', {})
    if not isinstance(vendors, dict):
        vendors = {}
    
    # We need to copy to ensure change detection works if it's a nested dict
    vendors = vendors.copy()
    vendors[vendor] = state_dict
    session['vendors'] = vendors

def load_all_vendor_data(session_id: str, collection=None):
    session = _get_session()
    if not session:
        return {}
    
    return session.get('vendors', {})

def load_vendor_data(session_id: str, vendor: str, collection=None):
    vendors = load_all_vendor_data(session_id, collection)
    data = vendors.get(vendor)
    if data:
        return _deserialize_vendor_state(data)
    return None

def load_session(session_id: str, collection=None, force_reload: bool = False):
    session = _get_session()
    if not session:
        return None
    
    # Construct SessionState
    from .phased_service import SessionState
    
    vendors_data = session.get('vendors', {})
    vendors = {}
    for v_name, v_data in vendors_data.items():
        if v_data:
            vendors[v_name] = _deserialize_vendor_state(v_data)

    # Helper for timestamp conversion
    def parse_dt(dt_str):
        if isinstance(dt_str, str):
            try:
                return datetime.fromisoformat(dt_str)
            except ValueError:
                return None
        return dt_str

    # vendors_list deprecated but we can populate it from keys
    from .clients.base import ModelVendor
    vendors_list = []
    for v in vendors.keys():
        try:
            vendors_list.append(ModelVendor(v))
        except ValueError:
            pass

    return SessionState(
        session_id=session_id,
        job_text=session.get("job_text", ""),
        cv_text=session.get("cv_text", ""),
        style_instructions=session.get("style_instructions", ""),
        search_result=session.get("search_result", []),
        metadata=session.get("metadata", {}),
        vendors=vendors,
        vendors_list=vendors_list
    )

def save_session(session_state, collection=None) -> None:
    # Save everything back to session
    save_session_common_data(
        session_state.session_id,
        session_state.job_text,
        session_state.cv_text,
        session_state.metadata,
        session_state.search_result,
        session_state.style_instructions
    )
    
    for v_name, v_state in session_state.vendors.items():
        save_vendor_data(session_state.session_id, v_name, v_state)

def get_session(session_id: str, collection=None):
    return load_session(session_id, collection)

def delete_session(session_id: str, collection=None) -> None:
    session = _get_session()
    if session:
        session.clear()

def clear_cache() -> None:
    pass # No-op
