"""
Cost tracking module for all API calls.

Tracks costs for:
- Translation API (Google Translate): $20 per million characters
- AI model APIs (already tracked in clients)
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


# Thread lock for concurrent writes
_lock = threading.Lock()


def get_cost_log_path() -> Path:
    """Get the path to the cost tracking JSON file.
    
    Uses environment variable API_COST_LOG_PATH if set, otherwise defaults to
    api_costs.json in the project root.
    """
    log_path = os.environ.get("API_COST_LOG_PATH", "api_costs.json")
    return Path(log_path)


def load_cost_data() -> Dict[str, Any]:
    """Load existing cost data from JSON file.
    
    Returns:
        Dictionary with cost data, or empty structure if file doesn't exist
    """
    cost_file = get_cost_log_path()
    
    if not cost_file.exists():
        return {
            "total_cost": 0.0,
            "by_service": {},
            "requests": []
        }
    
    try:
        with open(cost_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARN] Failed to load cost data from {cost_file}: {e}")
        return {
            "total_cost": 0.0,
            "by_service": {},
            "requests": []
        }


def save_cost_data(data: Dict[str, Any]) -> None:
    """Save cost data to JSON file atomically.
    
    Args:
        data: Cost data dictionary to save
    """
    cost_file = get_cost_log_path()
    
    try:
        # Write to temporary file first, then rename (atomic on Unix)
        temp_file = cost_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        temp_file.rename(cost_file)
    except IOError as e:
        print(f"[ERROR] Failed to save cost data to {cost_file}: {e}")


def track_api_cost(
    service: str,
    cost: float,
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None
) -> None:
    """Track cost for an API call.
    
    Args:
        service: Name of the service (e.g., "translate", "openai", "anthropic")
        cost: Cost in USD
        metadata: Additional metadata about the request (e.g., character count, model name)
        user_id: Optional user ID for per-user tracking
    """
    with _lock:
        data = load_cost_data()
        
        # Update total cost
        data["total_cost"] = data.get("total_cost", 0.0) + cost
        
        # Update per-service cost
        if "by_service" not in data:
            data["by_service"] = {}
        
        if service not in data["by_service"]:
            data["by_service"][service] = {
                "total_cost": 0.0,
                "request_count": 0
            }
        
        data["by_service"][service]["total_cost"] += cost
        data["by_service"][service]["request_count"] += 1
        
        # Track per-user costs if user_id provided
        if user_id:
            if "by_user" not in data:
                data["by_user"] = {}
            
            if user_id not in data["by_user"]:
                data["by_user"][user_id] = {
                    "total_cost": 0.0,
                    "by_service": {}
                }
            
            data["by_user"][user_id]["total_cost"] += cost
            
            if service not in data["by_user"][user_id]["by_service"]:
                data["by_user"][user_id]["by_service"][service] = {
                    "total_cost": 0.0,
                    "request_count": 0
                }
            
            data["by_user"][user_id]["by_service"][service]["total_cost"] += cost
            data["by_user"][user_id]["by_service"][service]["request_count"] += 1
        
        # Add request record
        if "requests" not in data:
            data["requests"] = []
        
        request_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "service": service,
            "cost": cost,
        }
        
        if user_id:
            request_record["user_id"] = user_id
        
        if metadata:
            request_record["metadata"] = metadata
        
        data["requests"].append(request_record)
        
        # Limit request history to last 10000 entries to prevent unbounded growth
        if len(data["requests"]) > 10000:
            data["requests"] = data["requests"][-10000:]
        
        save_cost_data(data)


def calculate_translation_cost(character_count: int) -> float:
    """Calculate Google Translate API cost.
    
    Google Translate charges $20 per million characters.
    
    Args:
        character_count: Total number of characters translated
    
    Returns:
        Cost in USD
    """
    return (character_count / 1_000_000) * 20.0


def get_cost_summary() -> Dict[str, Any]:
    """Get a summary of all tracked costs.
    
    Returns:
        Dictionary with cost summary
    """
    data = load_cost_data()
    
    summary = {
        "total_cost": data.get("total_cost", 0.0),
        "by_service": data.get("by_service", {}),
        "total_requests": len(data.get("requests", [])),
    }
    
    if "by_user" in data:
        summary["by_user"] = data["by_user"]
    
    return summary
