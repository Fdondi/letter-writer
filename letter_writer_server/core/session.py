import os
import pickle
import fcntl
import time
import secrets
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional
from fastapi import Request, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature
from starlette.middleware.base import BaseHTTPMiddleware

from letter_writer_server.core.config import settings

logger = logging.getLogger(__name__)

# In-memory session storage (per-worker cache, NOT authoritative — filesystem is)
_SESSION_STORAGE: Dict[str, Dict[str, Any]] = {}
_STORAGE_LOCK = Lock()
SESSION_STORAGE_DIR = Path(os.environ.get("SESSION_STORAGE_DIR", "/tmp/fastapi_sessions"))

def _get_session_file_path(session_key: str) -> Path:
    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STORAGE_DIR / f"{session_key}.session"

def _get_lock_file_path(session_key: str) -> Path:
    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STORAGE_DIR / f"{session_key}.lock"

def _load_from_filesystem(session_key: str) -> Optional[Dict[str, Any]]:
    try:
        file_path = _get_session_file_path(session_key)
        if file_path.exists():
            with open(file_path, 'rb') as f:
                return pickle.load(f)
    except Exception as e:
        logger.warning(f"Failed to load session {session_key} from filesystem: {e}")
    return None

def _save_to_filesystem(session_key: str, data: Dict[str, Any]) -> None:
    try:
        file_path = _get_session_file_path(session_key)
        # Write to temp file then rename for atomicity
        tmp_path = file_path.with_suffix('.tmp')
        with open(tmp_path, 'wb') as f:
            pickle.dump(data, f)
        tmp_path.rename(file_path)
    except Exception as e:
        logger.error(f"Failed to save session {session_key} to filesystem: {e}")

def _delete_from_filesystem(session_key: str) -> None:
    try:
        file_path = _get_session_file_path(session_key)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to delete session {session_key} from filesystem: {e}")

class Session(dict):
    def __init__(self, initial_data: Dict[str, Any] = None, session_key: str = None):
        super().__init__(initial_data or {})
        self.session_key = session_key
        self.modified = False
        self.accessed = False
        self._dirty_keys: set = set()  # Track which keys were actually written

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self.modified = True
        self._dirty_keys.add(key)

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self.modified = True
        self._dirty_keys.add(key)
    
    def get(self, key: Any, default: Any = None) -> Any:
        self.accessed = True
        return super().get(key, default)
    
    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return self[key]
        self.modified = True
        self._dirty_keys.add(key)
        return super().setdefault(key, default)

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)
        self.modified = True
        # Track all keys being updated
        if args:
            if isinstance(args[0], dict):
                self._dirty_keys.update(args[0].keys())
            else:
                self._dirty_keys.update(k for k, v in args[0])
        self._dirty_keys.update(kwargs.keys())

    def pop(self, *args) -> Any:
        self.modified = True
        if args:
            self._dirty_keys.add(args[0])
        return super().pop(*args)

    def clear(self) -> None:
        self._dirty_keys.update(self.keys())  # Mark all current keys as dirty
        super().clear()
        self.modified = True

class SessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret_key: str, cookie_name: str = "session", max_age: int = 60 * 60 * 24 * 30):
        super().__init__(app)
        self.signer = URLSafeTimedSerializer(secret_key, salt="cookie-session")
        self.cookie_name = cookie_name
        self.max_age = max_age

    async def dispatch(self, request: Request, call_next):
        session_key = None
        session_data = {}
        
        signed_session_id = request.cookies.get(self.cookie_name)
        if signed_session_id:
            try:
                session_key = self.signer.loads(signed_session_id, max_age=self.max_age)
                # Load from server-side storage
                # Always check filesystem first (authoritative source across workers)
                with _STORAGE_LOCK:
                    fs_data = _load_from_filesystem(session_key)
                    if fs_data:
                        session_data = fs_data
                        _SESSION_STORAGE[session_key] = session_data
                    elif session_key in _SESSION_STORAGE:
                        session_data = _SESSION_STORAGE[session_key]
                    else:
                        session_data = {} # Session expired or lost
                        session_key = None # Generate new one
            except (BadSignature, Exception):
                session_key = None
        
        # Create session object
        if not session_key:
            session_key = secrets.token_urlsafe(32)
            session_data = {}
            
        
        request.state.session = Session(session_data, session_key)
        request.scope["session"] = request.state.session
        
        response = await call_next(request)
        
        # Save session if modified
        if request.state.session.modified:
            lock_path = _get_lock_file_path(session_key)
            try:
                with open(lock_path, 'w') as lock_file:
                    # File lock ensures cross-worker atomicity
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        # ALWAYS re-read from filesystem to get latest cross-worker state.
                        # This is critical with multiple uvicorn workers — each worker's
                        # _SESSION_STORAGE is a separate process-local dict and goes stale
                        # as soon as another worker saves.
                        existing_data = _load_from_filesystem(session_key) or {}

                        # Update expiration
                        existing_data['_expires_at'] = time.time() + self.max_age
                        
                        session_obj = request.state.session
                        dirty_keys = session_obj._dirty_keys
                        
                        # Only merge keys that were actually written during this request.
                        # This prevents stale loaded data from overwriting newer data
                        # saved by another worker between our load and save.
                        for key in dirty_keys:
                            if key not in session_obj:
                                # Key was deleted in this request
                                existing_data.pop(key, None)
                                continue
                            value = session_obj[key]
                            if key == 'vendors' and isinstance(value, dict) and isinstance(existing_data.get('vendors'), dict):
                                merged = existing_data['vendors'].copy()
                                merged.update(value)
                                existing_data['vendors'] = merged
                            elif key == 'metadata' and isinstance(value, dict) and isinstance(existing_data.get('metadata'), dict):
                                merged = existing_data['metadata'].copy()
                                merged.update(value)
                                existing_data['metadata'] = merged
                            else:
                                existing_data[key] = value
                        
                        _SESSION_STORAGE[session_key] = existing_data
                        _save_to_filesystem(session_key, existing_data)
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception as e:
                logger.error(f"Failed to save session {session_key}: {e}")

            # Set cookie
            response.set_cookie(
                self.cookie_name,
                self.signer.dumps(session_key),
                max_age=self.max_age,
                httponly=True,
                samesite="lax",
                secure=True # Always secure for now, maybe config?
            )
        
        return response

def get_session(request: Request) -> Session:
    return request.state.session
