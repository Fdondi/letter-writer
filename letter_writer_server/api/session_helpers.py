"""Helper functions for Django cookie-based sessions.

This module provides a compatible interface to the Firestore session store,
but uses Django's signed cookie sessions instead. All data is stored client-side
in encrypted cookies, eliminating Firestore read/write costs.
"""
from typing import Dict, Any, Optional
from django.http import HttpRequest


def get_session_id(request: HttpRequest) -> str:
    """Get or create a session ID from Django session.
    
    Django sessions automatically create a session key if one doesn't exist.
    We use it as the session_id for compatibility with existing code.
    """
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def save_session_common_data(
    request: HttpRequest,
    job_text: str = "",
    cv_text: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    search_result: Optional[list] = None,
) -> None:
    """Save common session data to Django cookie session.
    
    This replaces the Firestore-based save_session_common_data.
    Data is stored in request.session and automatically saved to cookie.
    """
    # Initialize session if needed
    if not request.session.session_key:
        request.session.create()
    
    # Get existing metadata or create new
    existing_metadata = request.session.get("metadata", {})
    if metadata:
        # Merge new metadata with existing
        if isinstance(existing_metadata, dict) and isinstance(metadata, dict):
            merged_metadata = existing_metadata.copy()
            merged_metadata.update(metadata)
            metadata = merged_metadata
        else:
            # If not dicts, just use new metadata
            metadata = metadata
    
    # Update session data
    request.session["job_text"] = job_text
    request.session["cv_text"] = cv_text
    request.session["metadata"] = metadata or {}
    if search_result is not None:
        request.session["search_result"] = search_result
    
    # Mark session as modified so it gets saved
    request.session.modified = True


def load_session_common_data(request: HttpRequest) -> Optional[Dict[str, Any]]:
    """Load common session data from Django cookie session.
    
    Returns None if session doesn't exist or is empty.
    Compatible with Firestore-based load_session_common_data interface.
    """
    if not request.session.session_key:
        return None
    
    # Check if session has any data
    if not any(key in request.session for key in ["job_text", "cv_text", "metadata"]):
        return None
    
    return {
        "session_id": request.session.session_key,
        "job_text": request.session.get("job_text", ""),
        "cv_text": request.session.get("cv_text", ""),
        "search_result": request.session.get("search_result", []),
        "metadata": request.session.get("metadata", {}),
    }


def save_vendor_data(
    request: HttpRequest,
    vendor: str,
    vendor_state: Any,
) -> None:
    """Save vendor-specific data to Django session.
    
    Vendor data is stored under request.session['vendors'][vendor].
    """
    if not request.session.session_key:
        request.session.create()
    
    # Initialize vendors dict if needed
    if "vendors" not in request.session:
        request.session["vendors"] = {}
    
    # Serialize vendor state
    vendor_data = {
        "top_docs": getattr(vendor_state, "top_docs", []),
        "company_report": getattr(vendor_state, "company_report", ""),
        "draft_letter": getattr(vendor_state, "draft_letter", ""),
        "final_letter": getattr(vendor_state, "final_letter", ""),
        "feedback": getattr(vendor_state, "feedback", ""),
        "cost": getattr(vendor_state, "cost", 0.0),
    }
    
    # Save vendor data
    request.session["vendors"][vendor] = vendor_data
    request.session.modified = True


def load_vendor_data(request: HttpRequest, vendor: str) -> Optional[Dict[str, Any]]:
    """Load vendor-specific data from Django session."""
    if not request.session.session_key:
        return None
    
    vendors = request.session.get("vendors", {})
    return vendors.get(vendor)


def load_all_vendor_data(request: HttpRequest) -> Dict[str, Dict[str, Any]]:
    """Load all vendor data from Django session."""
    if not request.session.session_key:
        return {}
    
    return request.session.get("vendors", {})


def restore_session_data(
    request: HttpRequest,
    job_text: str = "",
    cv_text: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    search_result: Optional[list] = None,
    vendors: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Restore full session data from client.
    
    Used when server restarts and loses in-memory sessions.
    Client sends all session data, server restores it.
    
    Returns the session_id (may be new if session was lost).
    """
    # Initialize session if needed
    if not request.session.session_key:
        request.session.create()
    
    # Restore all session data
    if job_text:
        request.session["job_text"] = job_text
    if cv_text:
        request.session["cv_text"] = cv_text
    if metadata:
        request.session["metadata"] = metadata
    if search_result is not None:
        request.session["search_result"] = search_result
    if vendors:
        # Ensure vendors dict exists and merge vendor data
        if "vendors" not in request.session:
            request.session["vendors"] = {}
        # Merge vendor data (don't overwrite existing, but update with restored data)
        for vendor_name, vendor_data in vendors.items():
            if vendor_data and isinstance(vendor_data, dict):
                # Ensure all required fields are present with defaults
                request.session["vendors"][vendor_name] = {
                    "top_docs": vendor_data.get("top_docs", []),
                    "company_report": vendor_data.get("company_report", ""),
                    "draft_letter": vendor_data.get("draft_letter", ""),
                    "final_letter": vendor_data.get("final_letter", ""),
                    "feedback": vendor_data.get("feedback", {}),
                    "cost": vendor_data.get("cost", 0.0),
                }
        print(f"[RESTORE] Restored {len(vendors)} vendors: {list(vendors.keys())}")
    
    request.session.modified = True
    return request.session.session_key


def check_session_exists(request: HttpRequest) -> bool:
    """Check if session exists and has data.
    
    Returns True if session exists with data, False if empty or missing.
    """
    if not request.session.session_key:
        return False
    
    # Check if session has any meaningful data
    return any(key in request.session for key in ["job_text", "cv_text", "metadata", "vendors"])


def get_full_session_state(request: HttpRequest) -> Optional[Dict[str, Any]]:
    """Get complete session state for restoring frontend UI.
    
    Returns all session data including common data and all vendor data.
    Used when user navigates back to restore their work.
    """
    if not request.session.session_key:
        return None
    
    # Check if session has any data
    if not check_session_exists(request):
        return None
    
    # Get common data
    common_data = load_session_common_data(request)
    if not common_data:
        return None
    
    # Get all vendor data
    vendors_data = load_all_vendor_data(request)
    
    # Combine into full state
    return {
        "session_id": request.session.session_key,
        "job_text": common_data.get("job_text", ""),
        "cv_text": common_data.get("cv_text", ""),
        "metadata": common_data.get("metadata", {}),
        "search_result": common_data.get("search_result", []),
        "vendors": vendors_data,
    }


def clear_session(request: HttpRequest) -> None:
    """Clear all session data.
    
    Called when:
    - User explicitly clicks "clear" button
    - Final data is saved/copied (user is done)
    """
    if request.session.session_key:
        request.session.flush()  # Clear and create new session
