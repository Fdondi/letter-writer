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


def _load_user_data_from_firestore(request: HttpRequest) -> Dict[str, str]:
    """Load user data (CV, style instructions) from Firestore. Returns dict with empty strings if not available."""
    import logging
    logger = logging.getLogger(__name__)
    
    result = {"cv_text": "", "style_instructions": ""}
    
    if not request.user.is_authenticated:
        logger.warning("Cannot load user data: user not authenticated")
        return result
    
    try:
        from letter_writer.firestore_store import get_user_data
        from datetime import datetime
        
        # Determine user_id: prefer Google UID if available (same logic as require_auth_user)
        user_id = None
        try:
            from allauth.socialaccount.models import SocialAccount
            social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
            if social_account:
                user_id = social_account.uid
                logger.info(f"Using Google UID for Firestore lookup: {user_id}")
        except (ImportError, Exception):
            pass
        
        if not user_id:
            user_id = str(request.user.id)
            logger.info(f"Using Django User ID for Firestore lookup: {user_id}")

        logger.info(f"Loading user data from Firestore for user {user_id} (cache disabled)")
        # Disable cache to ensure we get the latest data even if updated in another process
        user_data = get_user_data(user_id, use_cache=False)
        
        # Load Style Instructions
        result["style_instructions"] = user_data.get("style_instructions", "")
        
        # Load CV
        revisions = user_data.get("cv_revisions", [])
        logger.info(f"Found {len(revisions)} CV revisions for user {user_id}")
        if not revisions:
            logger.warning(f"No CV revisions found for user {user_id}")
            return result
        
        # Get the latest revision by comparing timestamps
        def get_datetime(rev):
            ts = rev.get("created_at")
            if ts is None:
                return datetime.min
            if hasattr(ts, "timestamp"):  # Firestore Timestamp
                return datetime.fromtimestamp(ts.timestamp())
            elif isinstance(ts, datetime):
                return ts
            elif isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    return datetime.min
            return datetime.min
        
        latest = max(revisions, key=get_datetime)
        cv_text = latest.get("content", "")
        result["cv_text"] = cv_text
        
        if cv_text:
            logger.info(f"Successfully loaded CV from Firestore for user {user_id} ({len(cv_text)} chars)")
        else:
            logger.warning(f"CV revision found but content is empty for user {user_id}")
            
        return result
    except Exception as e:
        # Log but don't fail - let the calling code handle missing data
        logger.error(f"Failed to load user data from Firestore for user {request.user.id}: {e}", exc_info=True)
        return result


def save_session_common_data(
    request: HttpRequest,
    job_text: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    search_result: Optional[list] = None,
    style_instructions: str = "",
    load_cv: bool = False,
) -> None:
    """Save common session data to in-memory Django session.
    
    Data is stored in request.session (in-memory, not cookies).
    
    Args:
        load_cv: If True, load CV and style instructions from Firestore and save to session (used during init/restore)
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
    
    # Preserve existing job_text if new value is empty
    # This prevents overwriting session data when clicking back without sending data
    # BUT: if old values are empty and new values are provided, restore from new values
    existing_job_text = request.session.get("job_text", "")
    
    # Determine final job_text: use new if non-empty, otherwise keep existing if it exists, otherwise empty
    if job_text and job_text.strip():
        request.session["job_text"] = job_text  # New value provided and non-empty
    elif existing_job_text and existing_job_text.strip():
        # Keep existing non-empty value if new value not provided or empty
        pass  # Don't change existing
    else:
        # Both empty - set to empty (either explicit empty or None becomes empty string)
        request.session["job_text"] = job_text if job_text is not None else ""
        
    # Handle style instructions (save if provided)
    if style_instructions:
        request.session["style_instructions"] = style_instructions

    # Load CV and Style Instructions from Firestore if requested (during init/restore)
    # Always load if requested, even if session already has them (ensures fresh data)
    if load_cv:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Loading user data into session (session_key={request.session.session_key})")
        user_data = _load_user_data_from_firestore(request)
        
        cv_text = user_data.get("cv_text", "")
        if cv_text:
            request.session["cv_text"] = cv_text
            logger.info(f"CV saved to session ({len(cv_text)} chars)")
        else:
            # If no CV found, set empty string so we know CV was checked
            request.session["cv_text"] = ""
            logger.warning("CV not found in Firestore, set empty string in session")
            
        instructions = user_data.get("style_instructions", "")
        if instructions:
            request.session["style_instructions"] = instructions
            logger.info(f"Style instructions saved to session ({len(instructions)} chars)")
    
    request.session["metadata"] = metadata or {}
    if search_result is not None:
        request.session["search_result"] = search_result
    
    # Mark session as modified so it gets saved
    request.session.modified = True


def load_session_common_data(request: HttpRequest) -> Optional[Dict[str, Any]]:
    """Load common session data from in-memory Django session.
    
    Returns None if session doesn't exist or is empty.
    Compatible with Firestore-based load_session_common_data interface.
    
    cv_text is read from in-memory session (loaded once during init/restore).
    Only loads from Firestore if missing from session (emergency restore).
    """
    if not request.session.session_key:
        return None
    
    # Check if session has any data
    if not any(key in request.session for key in ["job_text", "cv_text", "metadata"]):
        return None
    
    job_text = request.session.get("job_text", "")
    cv_text = request.session.get("cv_text", "")
    style_instructions = request.session.get("style_instructions", "")
    
    # If cv_text is missing from session, load from Firestore (emergency restore)
    # This should only happen if session was lost or CV wasn't loaded during init
    if not cv_text or not cv_text.strip():
        user_data = _load_user_data_from_firestore(request)
        cv_text = user_data.get("cv_text", "")
        # Save to session for future requests (emergency restore)
        if cv_text:
            request.session["cv_text"] = cv_text
            request.session.modified = True
            
        # Also opportunistic restore of style instructions if missing
        if not style_instructions:
            style_instructions = user_data.get("style_instructions", "")
            if style_instructions:
                request.session["style_instructions"] = style_instructions
                request.session.modified = True
    
    return {
        "session_id": request.session.session_key,
        "job_text": job_text,
        "cv_text": cv_text,
        "style_instructions": style_instructions,
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
    metadata: Optional[Dict[str, Any]] = None,
    search_result: Optional[list] = None,
    vendors: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Restore full session data from client.
    
    Used when server restarts and loses in-memory sessions.
    Client sends session data, server restores it.
    
    NOTE: cv_text and style_instructions are NEVER restored from client - 
    loaded from Firestore and saved to in-memory session during restore.
    
    Returns the session_id (may be new if session was lost).
    """
    # Initialize session if needed
    if not request.session.session_key:
        request.session.create()
    
    # Restore session data
    if job_text:
        request.session["job_text"] = job_text
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
    
    # Load user data from Firestore and save to in-memory session (one-time during restore)
    # This ensures CV and instructions are available in session for subsequent requests
    user_data = _load_user_data_from_firestore(request)
    
    cv_text = user_data.get("cv_text", "")
    if cv_text:
        request.session["cv_text"] = cv_text
        
    style_instructions = user_data.get("style_instructions", "")
    if style_instructions:
        request.session["style_instructions"] = style_instructions
    
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
    # NOTE: cv_text is NOT included - it's never sent to frontend in compose mode
    # CV is only sent to frontend in the personal data tab
    return {
        "session_id": request.session.session_key,
        "job_text": common_data.get("job_text", ""),
        "style_instructions": common_data.get("style_instructions", ""),
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
