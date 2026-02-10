from typing import Dict, Any, List

_IN_FLIGHT_REQUESTS: Dict[str, Any] = {}

def get_in_flight_requests() -> Dict[str, Any]:
    """Return current in-flight requests."""
    return _IN_FLIGHT_REQUESTS

def clear_in_flight_requests() -> int:
    """Clear all in-flight requests and return count."""
    count = len(_IN_FLIGHT_REQUESTS)
    _IN_FLIGHT_REQUESTS.clear()
    return count

def add_in_flight_request(request_id: str, data: Any):
    """Add a request to in-flight tracking."""
    _IN_FLIGHT_REQUESTS[request_id] = data

def remove_in_flight_request(request_id: str):
    """Remove a request from in-flight tracking."""
    if request_id in _IN_FLIGHT_REQUESTS:
        del _IN_FLIGHT_REQUESTS[request_id]
