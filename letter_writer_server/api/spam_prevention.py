"""Spam prevention mechanism to prevent duplicate concurrent requests."""
import hashlib
import json
import threading
from functools import wraps
from typing import Callable, Any
from django.http import HttpRequest, JsonResponse


# Global thread-safe storage for in-flight requests
_in_flight_requests: dict[str, bool] = {}
_lock = threading.Lock()


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
        if data:
            # Create a stable hash of the request data (sorted keys for consistency)
            body_str = str(sorted(data.items()))
            body_hash = hashlib.md5(body_str.encode()).hexdigest()[:8]
            key_parts.append(f"hash:{body_hash}")
    
    # Add vendor if specified (for vendor-specific endpoints)
    if vendor:
        key_parts.append(f"vendor:{vendor}")
    
    return "|".join(key_parts)


def prevent_duplicate_requests(
    endpoint_path: str | None = None,
    use_vendor_in_key: bool = False,
):
    """Decorator to prevent duplicate concurrent requests.
    
    Args:
        endpoint_path: Custom path identifier. If None, uses the view function name.
        use_vendor_in_key: If True, includes vendor parameter in the request key
                          (for vendor-specific endpoints like /phases/background/<vendor>/)
    
    Returns early with 409 Conflict if an identical request is already in-flight.
    """
    def decorator(view_func: Callable) -> Callable:
        path = endpoint_path or view_func.__name__
        
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> JsonResponse | Any:
            # Extract vendor from kwargs if it exists (from URL path like /phases/background/<vendor>/)
            vendor = kwargs.get("vendor") if use_vendor_in_key else None
            
            # Parse request body if it's a POST/PUT request
            data = None
            if request.method in ("POST", "PUT", "PATCH"):
                try:
                    body = request.body or b"{}"
                    data = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # If we can't parse JSON, let the view handle the error
                    pass
            
            # Generate unique key for this request
            request_key = _generate_request_key(request, path, data, vendor)
            
            # Check if request is already in-flight
            with _lock:
                if request_key in _in_flight_requests:
                    # Request already in-flight, return conflict
                    return JsonResponse(
                        {"detail": "A duplicate request is already in progress. Please wait for it to complete."},
                        status=409
                    )
                # Mark request as in-flight
                _in_flight_requests[request_key] = True
            
            try:
                # Execute the view function
                response = view_func(request, *args, **kwargs)
                return response
            finally:
                # Remove from in-flight requests
                with _lock:
                    _in_flight_requests.pop(request_key, None)
        
        return wrapper
    return decorator
