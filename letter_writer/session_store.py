from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, Optional, TYPE_CHECKING
from threading import Lock

from pymongo import MongoClient
from qdrant_client.models import ScoredPoint

from .mongo_store import get_db, get_mongo_client
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


def _serialize_scored_point(point: ScoredPoint) -> dict:
    """Serialize a ScoredPoint to a dict."""
    # Try using Pydantic's model_dump if available (ScoredPoint is a Pydantic model)
    if hasattr(point, 'model_dump'):
        return point.model_dump()
    
    # Fallback to manual serialization
    result = {
        "id": str(point.id) if hasattr(point, 'id') and point.id is not None else None,
        "score": float(point.score) if hasattr(point, 'score') and point.score is not None else None,
        "payload": dict(point.payload) if hasattr(point, 'payload') and point.payload else {},
        "vector": point.vector if hasattr(point, 'vector') else None,
    }
    # Include version if it exists (required by newer versions of qdrant_client)
    if hasattr(point, 'version'):
        result["version"] = point.version
    return result


def _deserialize_scored_point(data: dict) -> ScoredPoint:
    """Deserialize a dict to a ScoredPoint."""
    # Try using Pydantic's model_validate if available
    if hasattr(ScoredPoint, 'model_validate'):
        return ScoredPoint.model_validate(data)
    
    # Fallback to manual deserialization
    # Build kwargs dict, only including fields that are present
    kwargs = {}
    if "id" in data and data["id"] is not None:
        kwargs["id"] = data["id"]
    if "score" in data and data["score"] is not None:
        kwargs["score"] = data["score"]
    if "payload" in data:
        kwargs["payload"] = data.get("payload", {})
    if "vector" in data:
        kwargs["vector"] = data.get("vector")
    # Version is required by newer versions of qdrant_client
    # Default to None if not present (for backward compatibility with old sessions)
    kwargs["version"] = data.get("version", None)
    
    return ScoredPoint(**kwargs)


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
    """Serialize SessionState to a dict for MongoDB storage."""
    return {
        "session_id": session.session_id,
        "job_text": session.job_text,
        "cv_text": session.cv_text,
        "qdrant_host": session.qdrant_host,
        "qdrant_port": session.qdrant_port,
        "search_result": [_serialize_scored_point(p) for p in session.search_result],
        "vendors": {k: _serialize_vendor_state(v) for k, v in session.vendors.items()},
        "metadata": session.metadata,
        "vendors_list": [v.value for v in session.vendors_list],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


def _deserialize_session(data: dict):
    """Deserialize a dict from MongoDB to SessionState."""
    # Import here to avoid circular dependency
    from .phased_service import SessionState, VendorPhaseState
    
    return SessionState(
        session_id=data["session_id"],
        job_text=data["job_text"],
        cv_text=data["cv_text"],
        qdrant_host=data["qdrant_host"],
        qdrant_port=data["qdrant_port"],
        search_result=[_deserialize_scored_point(p) for p in data.get("search_result", [])],
        vendors={k: _deserialize_vendor_state(v) for k, v in data.get("vendors", {}).items()},
        metadata=data.get("metadata", {}),
        vendors_list=[ModelVendor(v) for v in data.get("vendors_list", [])],
    )


def ensure_session_indexes(db) -> None:
    """Ensure MongoDB indexes exist for sessions and session_vendors collections, including TTL index."""
    # Create TTL index on updated_at field (expires after SESSION_TTL_DAYS)
    # MongoDB TTL indexes delete documents where the date field is older than expireAfterSeconds
    ttl_seconds = SESSION_TTL_DAYS * 24 * 60 * 60  # Convert days to seconds
    try:
        db.sessions.create_index(
            [("updated_at", 1)],
            expireAfterSeconds=ttl_seconds,
            name="updated_at_ttl",
        )
    except Exception:
        # Index might already exist, try to recreate with new TTL
        try:
            db.sessions.drop_index("updated_at_ttl")
            db.sessions.create_index(
                [("updated_at", 1)],
                expireAfterSeconds=ttl_seconds,
                name="updated_at_ttl",
            )
        except Exception:
            pass  # Ignore if it fails
    
    # Create index on session_id for fast lookups
    try:
        db.sessions.create_index("session_id", unique=True)
    except Exception:
        pass  # Index might already exist
    
    # Create indexes for session_vendors collection (vendor-specific data)
    try:
        # Compound index on (session_id, vendor) for fast lookups
        db.session_vendors.create_index(
            [("session_id", 1), ("vendor", 1)],
            unique=True,
            name="session_vendor_unique",
        )
        # TTL index for vendor data
        db.session_vendors.create_index(
            [("updated_at", 1)],
            expireAfterSeconds=ttl_seconds,
            name="updated_at_ttl",
        )
        # Index on session_id for finding all vendors for a session
        db.session_vendors.create_index("session_id")
    except Exception:
        pass  # Indexes might already exist


def save_session(session, db=None) -> None:
    """Save a session to MongoDB and update the in-memory cache."""
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    doc = _serialize_session(session)
    now = datetime.utcnow()
    doc["updated_at"] = now
    
    # Upsert to MongoDB - set created_at only on insert, not on update
    existing = db.sessions.find_one({"session_id": session.session_id})
    if existing is None:
        doc["created_at"] = now
    else:
        # Preserve existing created_at
        doc["created_at"] = existing.get("created_at", now)
    
    # Upsert to MongoDB
    db.sessions.update_one(
        {"session_id": session.session_id},
        {"$set": doc},
        upsert=True,
    )
    
    # Update in-memory cache
    with CACHE_LOCK:
        SESSION_CACHE[session.session_id] = session


def save_session_common_data(session_id: str, job_text: str, cv_text: str,
                             qdrant_host: str, qdrant_port: int,
                             metadata: dict, search_result: list = None, db=None) -> None:
    """Save or update common session data. Called by extraction phase or start phased flow.
    
    This is the ONLY place that writes common session data. Uses lock for session creation.
    """
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    now = datetime.utcnow()
    
    # Use lock only for session creation to prevent duplicate sessions
    with SESSION_CREATE_LOCK:
        existing = db.sessions.find_one({"session_id": session_id})
        
        if existing is None:
            # Create new session
            db.sessions.insert_one({
                "session_id": session_id,
                "job_text": job_text,
                "cv_text": cv_text,
                "qdrant_host": qdrant_host,
                "qdrant_port": qdrant_port,
                "search_result": [_serialize_scored_point(p) for p in (search_result or [])],
                "metadata": metadata,
                "created_at": now,
                "updated_at": now,
            })
        else:
            # Update existing session - merge metadata, update other fields
            update_op = {
                "$set": {
                    "job_text": job_text,
                    "cv_text": cv_text,
                    "qdrant_host": qdrant_host,
                    "qdrant_port": qdrant_port,
                    "updated_at": now,
                },
            }
            # Merge metadata (don't overwrite existing)
            for vendor_name, extraction_data in metadata.items():
                update_op["$set"][f"metadata.{vendor_name}"] = extraction_data
            
            # Update search_result if provided
            if search_result is not None:
                update_op["$set"]["search_result"] = [_serialize_scored_point(p) for p in search_result]
            
            db.sessions.update_one(
                {"session_id": session_id},
                update_op,
            )


def load_session_common_data(session_id: str, db=None):
    """Load common session data (job_text, cv_text, metadata, search_result, etc.)."""
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    doc = db.sessions.find_one({"session_id": session_id})
    if doc is None:
        return None
    
    return {
        "session_id": doc["session_id"],
        "job_text": doc.get("job_text", ""),
        "cv_text": doc.get("cv_text", ""),
        "qdrant_host": doc.get("qdrant_host", "localhost"),
        "qdrant_port": doc.get("qdrant_port", 6333),
        "search_result": [_deserialize_scored_point(p) for p in doc.get("search_result", [])],
        "metadata": doc.get("metadata", {}),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def save_vendor_data(session_id: str, vendor: str, vendor_state, db=None) -> None:
    """Atomically save vendor-specific data to separate collection.
    
    Each vendor has their own document keyed by (session_id, vendor).
    This is completely lock-free - vendors can work in parallel.
    """
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    # Import here to avoid circular dependency
    vendor_data = _serialize_vendor_state(vendor_state)
    
    now = datetime.utcnow()
    
    # Upsert vendor-specific data - completely independent from other vendors
    db.session_vendors.update_one(
        {
            "session_id": session_id,
            "vendor": vendor,
        },
        {
            "$set": {
                "session_id": session_id,
                "vendor": vendor,
                **vendor_data,  # Unpack vendor state data
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )


def load_vendor_data(session_id: str, vendor: str, db=None):
    """Load vendor-specific data."""
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    doc = db.session_vendors.find_one({
        "session_id": session_id,
        "vendor": vendor,
    })
    
    if doc is None:
        return None
    
    return _deserialize_vendor_state(doc)


def load_all_vendor_data(session_id: str, db=None):
    """Load all vendor data for a session."""
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    cursor = db.session_vendors.find({"session_id": session_id})
    result = {}
    for doc in cursor:
        vendor = doc["vendor"]
        result[vendor] = _deserialize_vendor_state(doc)
    
    return result


# Deprecated - use save_session_common_data instead
def ensure_session_exists(session_id: str, job_text: str, cv_text: str, 
                         qdrant_host: str, qdrant_port: int, 
                         vendor_metadata: dict, db=None) -> None:
    """Deprecated: Use save_session_common_data instead."""
    save_session_common_data(
        session_id=session_id,
        job_text=job_text,
        cv_text=cv_text,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        metadata=vendor_metadata,
        db=db,
    )


def load_session(session_id: str, db=None, force_reload: bool = False):
    """Load a session from MongoDB if not in cache. Returns None if not found.
    
    Also loads vendor data from the session_vendors collection.
    
    Args:
        session_id: The session ID to load
        db: Optional database connection
        force_reload: If True, bypass cache and reload from MongoDB
    """
    # Check cache first (unless forcing reload)
    if not force_reload:
        with CACHE_LOCK:
            if session_id in SESSION_CACHE:
                return SESSION_CACHE[session_id]
    
    # Load from MongoDB
    if db is None:
        db = get_db()
    
    ensure_session_indexes(db)
    
    doc = db.sessions.find_one({"session_id": session_id})
    if doc is None:
        return None
    
    try:
        session = _deserialize_session(doc)
        
        # Load vendor data from separate collection
        vendor_data = load_all_vendor_data(session_id, db=db)
        if vendor_data:
            # Update session.vendors with data from session_vendors collection
            session.vendors.update(vendor_data)
        
        # Update cache
        with CACHE_LOCK:
            SESSION_CACHE[session_id] = session
        return session
    except Exception as e:
        # If deserialization fails, raise a more descriptive error
        # This is better than returning None, which would cause "Invalid session_id" error
        import traceback
        error_msg = f"Failed to deserialize session {session_id}: {e}"
        print(f"Error deserializing session {session_id}: {e}")
        traceback.print_exc()
        # Raise a ValueError with the actual error so it's clear what went wrong
        raise ValueError(error_msg) from e


def get_session(session_id: str, db=None):
    """Get a session from cache or MongoDB. Returns None if not found."""
    return load_session(session_id, db)


def delete_session(session_id: str, db=None) -> None:
    """Delete a session from MongoDB and cache."""
    if db is None:
        db = get_db()
    
    db.sessions.delete_one({"session_id": session_id})
    
    with CACHE_LOCK:
        SESSION_CACHE.pop(session_id, None)


def clear_cache() -> None:
    """Clear the in-memory cache (useful for testing or memory management)."""
    with CACHE_LOCK:
        SESSION_CACHE.clear()

