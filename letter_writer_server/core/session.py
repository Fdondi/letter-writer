import json
import os
import pickle
import fcntl
import time
import secrets
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional
from fastapi import Request, Response, HTTPException, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature
from starlette.middleware.base import BaseHTTPMiddleware

from letter_writer_server.core.config import settings

logger = logging.getLogger(__name__)

# In-memory session storage (per-worker cache, NOT authoritative — filesystem is)
_SESSION_STORAGE: Dict[str, Dict[str, Any]] = {}
_STORAGE_LOCK = Lock()
SESSION_STORAGE_DIR = Path(os.environ.get("SESSION_STORAGE_DIR", "/tmp/fastapi_sessions"))
AGENTIC_LAST_POLL_AT_KEY = "_agentic_last_poll_at"

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
                raw = f.read()
            # Try JSON first; fall back to pickle for legacy sessions.
            try:
                return json.loads(raw.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning(f"Session {session_key}: falling back to pickle (legacy format)")
                return pickle.loads(raw)  # noqa: S301 — legacy migration only
    except Exception as e:
        logger.warning(f"Failed to load session {session_key} from filesystem: {e}")
    return None

def _save_to_filesystem(session_key: str, data: Dict[str, Any]) -> None:
    try:
        file_path = _get_session_file_path(session_key)
        # Directory can disappear in container restarts/cleanup windows.
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp file then rename for atomicity
        tmp_path = file_path.with_suffix('.tmp')
        serialized = json.dumps(data, default=str).encode('utf-8')
        with open(tmp_path, 'wb') as f:
            f.write(serialized)
        try:
            tmp_path.rename(file_path)
        except FileNotFoundError:
            # Race-safe retry: ensure parent exists and rewrite temp once.
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, 'wb') as f:
                f.write(serialized)
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


def get_agentic_last_poll_at_from_storage(session_key: str) -> float:
    """Load session from filesystem and return agentic heartbeat timestamp (for idle abort checks)."""
    data = _load_from_filesystem(session_key)
    if not data:
        return 0.0
    return float(data.get(AGENTIC_LAST_POLL_AT_KEY) or 0.0)


def load_session_from_storage(session_key: str) -> Dict[str, Any]:
    """Load full session dict from disk (e.g. for background feedback step)."""
    data = _load_from_filesystem(session_key)
    return data if data is not None else {}


def save_session_to_storage(session_key: str, data: Dict[str, Any]) -> None:
    """Persist full session dict to disk (e.g. after background feedback step)."""
    lock_path = _get_lock_file_path(session_key)
    try:
        with open(lock_path, 'w') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                _save_to_filesystem(session_key, data)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        # Fallback best-effort write if lock acquisition fails unexpectedly.
        _save_to_filesystem(session_key, data)


def persist_agentic_last_poll_at(session_key: str, last_poll_at: float) -> None:
    """Record that the browser just polled (client still wants results). Persisted immediately
    on every poll so agent duration has no effect on the abort check."""
    lock_path = _get_lock_file_path(session_key)
    try:
        with open(lock_path, 'w') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                data = _load_from_filesystem(session_key)
                if data is None:
                    data = {}
                prev = float(data.get(AGENTIC_LAST_POLL_AT_KEY) or 0.0)
                data[AGENTIC_LAST_POLL_AT_KEY] = max(prev, float(last_poll_at))
                _save_to_filesystem(session_key, data)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        data = _load_from_filesystem(session_key) or {}
        prev = float(data.get(AGENTIC_LAST_POLL_AT_KEY) or 0.0)
        data[AGENTIC_LAST_POLL_AT_KEY] = max(prev, float(last_poll_at))
        _save_to_filesystem(session_key, data)


def agentic_processing_lock_path(session_key: str) -> Path:
    """Path for per-session lock so only one poll request runs work at a time."""
    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STORAGE_DIR / f"{session_key}.agentic_work.lock"


def try_acquire_agentic_lock(session_key: str, timeout_seconds: float = 120.0) -> bool:
    """Create lock file if not present or stale. Returns True if acquired."""
    lock_path = agentic_processing_lock_path(session_key)
    try:
        if lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age < timeout_seconds:
                return False
            lock_path.unlink(missing_ok=True)
        lock_path.write_text(str(time.time()))
        return True
    except Exception:
        return False


def release_agentic_lock(session_key: str) -> None:
    try:
        agentic_processing_lock_path(session_key).unlink(missing_ok=True)
    except Exception:
        pass


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
            active_session_key = request.state.session.session_key or session_key
            lock_path = _get_lock_file_path(active_session_key)
            try:
                with open(lock_path, 'w') as lock_file:
                    # File lock ensures cross-worker atomicity
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        # ALWAYS re-read from filesystem to get latest cross-worker state.
                        # This is critical with multiple uvicorn workers — each worker's
                        # _SESSION_STORAGE is a separate process-local dict and goes stale
                        # as soon as another worker saves.
                        existing_data = _load_from_filesystem(active_session_key) or {}

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
                        
                        _SESSION_STORAGE[active_session_key] = existing_data
                        _save_to_filesystem(active_session_key, existing_data)
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception as e:
                logger.error(f"Failed to save session {active_session_key}: {e}")

            # Set cookie unless endpoint requested invalidation (e.g., /api/phases/clear/).
            if not getattr(request.state, "skip_session_cookie_set", False):
                response.set_cookie(
                    self.cookie_name,
                    self.signer.dumps(active_session_key),
                    max_age=self.max_age,
                    httponly=True,
                    samesite="lax",
                    secure=True # Always secure for now, maybe config?
                )
        
        return response

def get_session(request: Request) -> Session:
    return request.state.session


# Re-authentication is required once every 24 hours.
AUTH_MAX_AGE_SECONDS = 60 * 60 * 24


def require_auth(session: Session = Depends(get_session)) -> dict:
    """FastAPI dependency: ensures the request has a valid, recently-authenticated user.

    Returns the user dict on success.  Raises 401 otherwise so callers don't need
    to check manually — just declare ``user: dict = Depends(require_auth)``.
    """
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    auth_time = float(session.get("auth_time") or 0)
    if time.time() - auth_time > AUTH_MAX_AGE_SECONDS:
        # Clear the stale user so the session can be reused after re-login.
        session.pop("user", None)
        session.pop("auth_time", None)
        raise HTTPException(
            status_code=401,
            detail="Session expired — please sign in again",
            headers={"X-Reauth-Required": "true"},
        )
    return user
