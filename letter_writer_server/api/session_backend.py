"""Custom Django session backend that stores data server-side (in-memory/filesystem).

Only the session key is stored in the cookie (small), while all session data
is stored server-side. This allows for large session data without hitting cookie size limits.

Data is stored in memory with optional filesystem backup for persistence across restarts.
"""
import json
import os
import pickle
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from django.contrib.sessions.backends.base import SessionBase, CreateError
from django.core.exceptions import SuspiciousOperation
from django.utils import timezone


# In-memory session storage
_SESSION_STORAGE: Dict[str, Dict[str, Any]] = {}
_STORAGE_LOCK = Lock()  # Global lock for read-modify-write operations (brief, per-session)

# Filesystem backup directory (optional, for persistence across restarts)
SESSION_STORAGE_DIR = Path(os.environ.get("DJANGO_SESSION_STORAGE_DIR", "/tmp/django_sessions"))


def _get_session_file_path(session_key: str) -> Path:
    """Get filesystem path for session backup."""
    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STORAGE_DIR / f"{session_key}.session"


def _load_from_filesystem(session_key: str) -> Optional[Dict[str, Any]]:
    """Load session data from filesystem backup."""
    try:
        file_path = _get_session_file_path(session_key)
        if file_path.exists():
            with open(file_path, 'rb') as f:
                return pickle.load(f)
    except Exception:
        pass
    return None


def _save_to_filesystem(session_key: str, data: Dict[str, Any]) -> None:
    """Save session data to filesystem backup."""
    try:
        file_path = _get_session_file_path(session_key)
        with open(file_path, 'wb') as f:
            pickle.dump(data, f)
    except Exception:
        pass  # Filesystem backup is optional, don't fail if it doesn't work


def _delete_from_filesystem(session_key: str) -> None:
    """Delete session data from filesystem backup."""
    try:
        file_path = _get_session_file_path(session_key)
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass


class SessionStore(SessionBase):
    """Custom session store that keeps data server-side, only key in cookie."""
    
    def __init__(self, session_key: Optional[str] = None):
        super().__init__(session_key)
        self._loaded = False
    
    def load(self) -> Dict[str, Any]:
        """Load session data from server-side storage."""
        if self.session_key is None:
            return {}
        
        with _STORAGE_LOCK:
            data = None
            
            # Try memory first
            if self.session_key in _SESSION_STORAGE:
                data = _SESSION_STORAGE[self.session_key].copy()
            
            # Try filesystem backup (for persistence across restarts)
            if data is None:
                data = _load_from_filesystem(self.session_key)
                if data:
                    # Restore to memory
                    _SESSION_STORAGE[self.session_key] = data.copy()
            
            # Check expiration
            if data:
                expires_at = data.get('_expires_at', 0)
                if expires_at < time.time():
                    # Session expired, delete it
                    _SESSION_STORAGE.pop(self.session_key, None)
                    _delete_from_filesystem(self.session_key)
                    data = None
        
        # Return data (without _expires_at - that's internal)
        if data:
            result = {k: v for k, v in data.items() if k != '_expires_at'}
            self._loaded = True
            return result
        
        # Session not found or expired
        self._loaded = True
        return {}
    
    def exists(self, session_key: str) -> bool:
        """Check if session exists."""
        with _STORAGE_LOCK:
            if session_key in _SESSION_STORAGE:
                return True
            return _get_session_file_path(session_key).exists()
    
    def create(self) -> None:
        """Create a new session."""
        while True:
            self._session_key = self._get_new_session_key()
            try:
                self.save(must_create=True)
            except CreateError:
                continue
            self.modified = True
            self._loaded = True
            return
    
    def save(self, must_create: bool = False) -> None:
        """Save session data to server-side storage.
        
        Uses merge strategy to allow concurrent writes from multiple vendors.
        Each vendor writes to independent keys (vendors[vendor_name]), so they
        can write in parallel without blocking each other.
        """
        if self.session_key is None:
            return self.create()
        
        if must_create and self.exists(self.session_key):
            raise CreateError
        
        # Get session data - use _get_session to get the actual data dict
        session_data = self._get_session(no_load=must_create)
        
        # Add expiration time (30 days default)
        expire_seconds = self.get_expiry_age()
        session_data['_expires_at'] = time.time() + expire_seconds
        
        # Use global lock only for the brief read-modify-write operation
        # This is fast enough that vendors won't block each other significantly
        with _STORAGE_LOCK:
            # Load existing data to merge (critical for concurrent writes)
            existing_data = _SESSION_STORAGE.get(self.session_key, {}).copy()
            
            # Merge strategy: preserve existing data, only update what changed
            # This allows multiple vendors to write concurrently without losing data
            for key, value in session_data.items():
                if key == '_expires_at':
                    # Always update expiration
                    existing_data[key] = value
                elif key == 'vendors' and isinstance(value, dict) and isinstance(existing_data.get('vendors'), dict):
                    # Special handling for vendors dict: merge vendor-specific data
                    # Each vendor writes to vendors[vendor_name], so merge at vendor level
                    merged_vendors = existing_data['vendors'].copy()
                    merged_vendors.update(value)  # Update/add vendor data
                    existing_data['vendors'] = merged_vendors
                elif key == 'metadata' and isinstance(value, dict) and isinstance(existing_data.get('metadata'), dict):
                    # Merge metadata (common + vendor-specific)
                    merged_metadata = existing_data['metadata'].copy()
                    merged_metadata.update(value)  # Update/add metadata
                    existing_data['metadata'] = merged_metadata
                else:
                    # For other keys, update directly (job_text, cv_text, etc.)
                    existing_data[key] = value
            
            # Save merged data back
            _SESSION_STORAGE[self.session_key] = existing_data
            
            # Optional: backup to filesystem
            if os.environ.get("DJANGO_SESSION_PERSIST", "false").lower() in ("1", "true", "yes"):
                _save_to_filesystem(self.session_key, existing_data)
        
        self._loaded = True
    
    def delete(self, session_key: Optional[str] = None) -> None:
        """Delete session from server-side storage."""
        if session_key is None:
            session_key = self.session_key
        
        if session_key is None:
            return
        
        with _STORAGE_LOCK:
            _SESSION_STORAGE.pop(session_key, None)
            _delete_from_filesystem(session_key)
    
    def flush(self) -> None:
        """Delete session and create a new one."""
        self.clear()
        self.delete()
        self._session_key = None
    
    @classmethod
    def clear_expired(cls) -> None:
        """Remove expired sessions from storage."""
        current_time = time.time()
        expired_keys = []
        
        with _STORAGE_LOCK:
            for key, data in _SESSION_STORAGE.items():
                expires_at = data.get('_expires_at', 0)
                if expires_at < current_time:
                    expired_keys.append(key)
            
            for key in expired_keys:
                _SESSION_STORAGE.pop(key, None)
                _delete_from_filesystem(key)
        
        # Also clean up filesystem
        if SESSION_STORAGE_DIR.exists():
            for file_path in SESSION_STORAGE_DIR.glob("*.session"):
                try:
                    with open(file_path, 'rb') as f:
                        data = pickle.load(f)
                        expires_at = data.get('_expires_at', 0)
                        if expires_at < current_time:
                            file_path.unlink()
                except Exception:
                    pass  # Skip corrupted files
