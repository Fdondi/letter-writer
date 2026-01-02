"""Spam prevention mechanism to prevent duplicate concurrent requests."""
import hashlib
import json
import threading
import time
from functools import wraps
from typing import Callable, Any
from django.http import HttpRequest, JsonResponse


# Global thread-safe storage for in-flight requests
# Stores: {request_key: timestamp_when_started}
_in_flight_requests: dict[str, float] = {}
_lock = threading.Lock()

# Maximum time a request can be "in-flight" before we consider it stale (5 minutes)
_STALE_REQUEST_TIMEOUT = 300.0

# Time after which we allow a new request to replace an in-flight one (for retries)
# This is shorter than stale timeout - allows retrying stuck requests
_REPLACE_REQUEST_TIMEOUT = 60.0  # 60 seconds - reasonable for AI operations


def get_in_flight_requests() -> dict[str, dict]:
    """Get current in-flight requests for debugging. Returns dict with request_key -> info."""
    current_time = time.time()
    with _lock:
        return {
            key: {
                "age_seconds": round(current_time - start_time, 2),
                "start_time": start_time,
                "is_stale": (current_time - start_time) > _STALE_REQUEST_TIMEOUT,
            }
            for key, start_time in _in_flight_requests.items()
        }


def clear_in_flight_requests() -> int:
    """Clear all in-flight requests. Returns number of cleared entries."""
    with _lock:
        count = len(_in_flight_requests)
        _in_flight_requests.clear()
        return count


def _get_client_ip(request: HttpRequest) -> str:
    """Get client IP address from request, handling proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', 'unknown')
    return ip


def _generate_request_key(
    request: HttpRequest,
    endpoint_path: str,
    data: dict | None = None,
    vendor: str | None = None,
    raw_body_hash: str | None = None,
) -> str:
    """Generate a unique key for identifying duplicate requests.
    
    Priority order for user identification:
    1. If user is authenticated: uses endpoint + user_id + (session_id if available) + vendor
    2. If session_id in request: uses endpoint + session_id + vendor
    3. Otherwise: uses endpoint + IP + request body hash (for anonymous requests)
    
    This ensures proper user isolation when authentication is enabled.
    """
    key_parts = [endpoint_path]
    
    # Use user ID if authenticated (best for multi-user scenarios)
    if hasattr(request, 'user') and request.user.is_authenticated:
        user_id = str(request.user.id)
        key_parts.append(f"user:{user_id}")
        # Still include session_id if available for per-session granularity
        if data and data.get("session_id"):
            key_parts.append(f"session:{data['session_id']}")
    # Fallback to session_id if no authenticated user
    elif data and data.get("session_id"):
        key_parts.append(f"session:{data['session_id']}")
    # Last resort: IP + body hash for anonymous requests
    else:
        ip = _get_client_ip(request)
        key_parts.append(f"ip:{ip}")
        # Use parsed data hash if available, otherwise use raw body hash
        if data:
            # Create a stable hash of the request data (sorted keys for consistency)
            body_str = str(sorted(data.items()))
            body_hash = hashlib.md5(body_str.encode()).hexdigest()[:8]
            key_parts.append(f"hash:{body_hash}")
        elif raw_body_hash:
            # Use raw body hash if we couldn't parse JSON
            key_parts.append(f"rawhash:{raw_body_hash}")
    
    # Add vendor if specified (for vendor-specific endpoints)
    if vendor:
        key_parts.append(f"vendor:{vendor}")
    
    return "|".join(key_parts)


def prevent_duplicate_requests(
    endpoint_path: str | None = None,
    use_vendor_in_key: bool = False,
    replace_timeout: float | None = None,
):
    """Decorator to prevent duplicate concurrent requests.
    
    Args:
        endpoint_path: Custom path identifier. If None, uses the view function name.
        use_vendor_in_key: If True, includes vendor parameter in the request key
                          (for vendor-specific endpoints like /phases/background/<vendor>/)
        replace_timeout: Time in seconds after which a new request can replace an in-flight one.
                        If None, uses default _REPLACE_REQUEST_TIMEOUT.
    
    Returns early with 409 Conflict if an identical request is already in-flight.
    """
    def decorator(view_func: Callable) -> Callable:
        path = endpoint_path or view_func.__name__
        replace_threshold = replace_timeout if replace_timeout is not None else _REPLACE_REQUEST_TIMEOUT
        
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> JsonResponse | Any:
            # Extract vendor from kwargs if it exists (from URL path like /phases/background/<vendor>/)
            vendor = kwargs.get("vendor") if use_vendor_in_key else None
            
            # Parse request body if it's a POST/PUT request
            data = None
            raw_body_hash = None
            is_heartbeat = False
            if request.method in ("POST", "PUT", "PATCH"):
                try:
                    body = request.body or b"{}"
                    data = json.loads(body)
                    # Check if frontend explicitly marks this as a heartbeat
                    is_heartbeat = data.get("_heartbeat", False) or data.get("is_heartbeat", False)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # If we can't parse JSON, hash the raw body to distinguish requests
                    body = request.body or b""
                    if body:
                        raw_body_hash = hashlib.md5(body).hexdigest()[:8]
            
            # Generate unique key for this request
            request_key = _generate_request_key(request, path, data, vendor, raw_body_hash)
            current_time = time.time()
            
            # Debug logging (can be removed in production)
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Spam prevention check: key={request_key}, method={request.method}, path={path}")
            
            # Check if request is already in-flight and clean up stale entries
            with _lock:
                # Clean up stale entries (requests that have been in-flight too long)
                stale_keys = [
                    key for key, start_time in _in_flight_requests.items()
                    if current_time - start_time > _STALE_REQUEST_TIMEOUT
                ]
                for stale_key in stale_keys:
                    _in_flight_requests.pop(stale_key, None)
                
                # Check if this specific request is already in-flight
                if request_key in _in_flight_requests:
                    start_time = _in_flight_requests[request_key]
                    age = current_time - start_time
                    # If it's stale (very old), remove it and allow the request
                    if age > _STALE_REQUEST_TIMEOUT:
                        _in_flight_requests.pop(request_key, None)
                    # If it's been running longer than replace threshold, allow replacement (retry)
                    elif age > replace_threshold:
                        logger.info(
                            f"Allowing request to replace in-flight request (age={round(age, 2)}s > {replace_threshold}s). "
                            f"This allows retrying potentially stuck requests. key={request_key}"
                        )
                        # Remove the old entry and allow this one
                        _in_flight_requests.pop(request_key, None)
                    # Very recent duplicate (< 0.1s) is likely React StrictMode double-render
                    # Treat as heartbeat to prevent duplicate expensive API calls
                    elif age < 0.1:
                        logger.info(
                            f"Very recent duplicate request detected (age={round(age, 3)}s). "
                            f"This is likely React StrictMode. Treating as heartbeat to prevent duplicate API calls. key={request_key}"
                        )
                        # Return "still processing" - don't allow replacement to avoid duplicate API calls
                        return JsonResponse(
                            {
                                "status": "processing",
                                "detail": "Request is still being processed. Very recent duplicate detected (likely React StrictMode).",
                                "request_key": request_key,
                                "age_seconds": round(age, 3),
                                "is_heartbeat": True,
                                "is_strictmode_duplicate": True,
                            },
                            status=202  # 202 Accepted - request is being processed
                        )
                    else:
                        # Request already in-flight and not old enough to auto-replace
                        # If explicitly marked as heartbeat, return "still processing" (frontend remembers)
                        # Otherwise, frontend doesn't remember - backend might have crashed/restarted or request is stuck
                        # Always allow replacement if frontend has no memory (trust frontend's state)
                        if is_heartbeat:
                            # Frontend explicitly says "yes, I remember, keep waiting"
                            logger.info(
                                f"Heartbeat request confirmed: key={request_key}, age={round(age, 2)}s. "
                                f"Frontend remembers the request, returning 'still processing'."
                            )
                            return JsonResponse(
                                {
                                    "status": "processing",
                                    "detail": "Request is still being processed. Frontend heartbeat received.",
                                    "request_key": request_key,
                                    "age_seconds": round(age, 2),
                                    "replace_after_seconds": replace_threshold,
                                    "is_heartbeat": True,
                                },
                                status=202  # 202 Accepted - request is being processed
                            )
                        else:
                            # Frontend doesn't remember (no heartbeat flag)
                            # This means frontend has no memory of the request, which could indicate:
                            # 1. Backend crashed/restarted (in-memory dict cleared, but maybe request still running?)
                            # 2. Frontend page refresh (lost state)
                            # 3. Stuck request that frontend gave up on
                            # Trust the frontend: if it doesn't remember, allow replacement
                            # This prevents blocking legitimate retries after backend issues
                            logger.info(
                                f"Duplicate request without heartbeat: key={request_key}, age={round(age, 2)}s. "
                                f"Frontend has no memory of request (possible backend crash/restart or stuck request). "
                                f"Allowing replacement - trusting frontend state over backend's in-memory tracking."
                            )
                            # Remove the old entry and allow this one to proceed
                            _in_flight_requests.pop(request_key, None)
                
                # Mark request as in-flight with current timestamp
                _in_flight_requests[request_key] = current_time
            
            try:
                # Execute the view function
                response = view_func(request, *args, **kwargs)
                return response
            except Exception:
                # If view raises an exception, we still want to clean up
                raise
            finally:
                # Remove from in-flight requests
                with _lock:
                    _in_flight_requests.pop(request_key, None)
        
        return wrapper
    return decorator
