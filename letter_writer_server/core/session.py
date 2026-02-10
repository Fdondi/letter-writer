import os
import pickle
import time
import secrets
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional
from fastapi import Request, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature
from starlette.middleware.base import BaseHTTPMiddleware

from letter_writer_server.core.config import settings

# In-memory session storage
_SESSION_STORAGE: Dict[str, Dict[str, Any]] = {}
_STORAGE_LOCK = Lock()
SESSION_STORAGE_DIR = Path(os.environ.get("SESSION_STORAGE_DIR", "/tmp/fastapi_sessions"))

def _get_session_file_path(session_key: str) -> Path:
    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STORAGE_DIR / f"{session_key}.session"

def _load_from_filesystem(session_key: str) -> Optional[Dict[str, Any]]:
    try:
        file_path = _get_session_file_path(session_key)
        if file_path.exists():
            with open(file_path, 'rb') as f:
                return pickle.load(f)
    except Exception:
        pass
    return None

def _save_to_filesystem(session_key: str, data: Dict[str, Any]) -> None:
    try:
        file_path = _get_session_file_path(session_key)
        with open(file_path, 'wb') as f:
            pickle.dump(data, f)
    except Exception:
        pass

def _delete_from_filesystem(session_key: str) -> None:
    try:
        file_path = _get_session_file_path(session_key)
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass

class Session(dict):
    def __init__(self, initial_data: Dict[str, Any] = None, session_key: str = None):
        super().__init__(initial_data or {})
        self.session_key = session_key
        self.modified = False
        self.accessed = False

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self.modified = True

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self.modified = True
    
    def get(self, key: Any, default: Any = None) -> Any:
        self.accessed = True
        return super().get(key, default)
    
    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return self[key]
        self.modified = True
        return super().setdefault(key, default)

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)
        self.modified = True

    def pop(self, *args) -> Any:
        self.modified = True
        return super().pop(*args)

    def clear(self) -> None:
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
                with _STORAGE_LOCK:
                    if session_key in _SESSION_STORAGE:
                        session_data = _SESSION_STORAGE[session_key]
                    else:
                        session_data = _load_from_filesystem(session_key)
                        if session_data:
                            _SESSION_STORAGE[session_key] = session_data
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
        
        response = await call_next(request)
        
        # Save session if modified
        if request.state.session.modified:
            with _STORAGE_LOCK:
                # Merge strategy similar to Django backend
                existing_data = _SESSION_STORAGE.get(session_key, {})
                if not existing_data:
                     existing_data = _load_from_filesystem(session_key) or {}

                # Update expiration
                existing_data['_expires_at'] = time.time() + self.max_age
                
                # Merge fields
                for key, value in request.state.session.items():
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
