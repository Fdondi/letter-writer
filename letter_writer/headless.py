"""Run the phased letter pipeline without an HTTP request (the opportunity batch).

``session_store`` reads the session from a thread-local request (``request.state.session``).
:func:`headless_session` binds a stand-in, so ``phased_service`` runs unchanged. The binding is per
thread: every worker thread enters its own ``headless_session``. Threads that phases start
themselves (research, feedback review) see no session, which only skips their audit events,
the same as under the web server.
"""
from __future__ import annotations

import copy
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from . import session_store
from .instruction_defaults import get_default_instruction
from .personal_data_sections import cv_text_with_extra_info, get_custom_instruction

logger = logging.getLogger(__name__)

# Session keys that never leave the batch: the CV, the signed-in user, and request audit logs
# (llm_io events carry whole prompts and would overflow Firestore's 1 MB document limit).
NOT_PERSISTED_KEYS = frozenset(
    {
        "cv_text",
        "user",
        "auth_time",
        session_store.APPLICATION_EVENT_LOG_KEY,
        session_store.PENDING_APPLICATION_EVENT_LOG_KEY,
        session_store.APPLICATION_LOG_BLOB_STORE_KEY,
        session_store.EVENT_LOG_FIRESTORE_DOCUMENT_ID_KEY,
    }
)


class HeadlessSession(dict):
    """The dict interface ``session_store`` needs, plus ``session_key``."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, session_key: str = "") -> None:
        super().__init__(data or {})
        self.session_key = session_key


@contextmanager
def headless_session(data: Dict[str, Any], session_key: str) -> Iterator[HeadlessSession]:
    """Bind ``data`` as this thread's session for the duration (restores the previous binding)."""
    sess = data if isinstance(data, HeadlessSession) else HeadlessSession(data, session_key)
    sess.session_key = session_key
    fake_request = SimpleNamespace(state=SimpleNamespace(session=sess))
    previous = session_store._get_current_request()
    session_store.set_current_request(fake_request)  # type: ignore[arg-type]
    try:
        yield sess
    finally:
        session_store.set_current_request(previous)  # type: ignore[arg-type]


def latest_cv_text(user_data: Dict[str, Any]) -> str:
    """Newest ``cv_revisions`` entry plus profile extra info, as ``/api/phases/init/`` builds it."""
    revisions = [r for r in (user_data.get("cv_revisions") or []) if isinstance(r, dict)]
    if not revisions:
        return ""
    latest = max(revisions, key=lambda r: str(r.get("created_at", "")))
    return cv_text_with_extra_info(str(latest.get("content", "") or ""), user_data)


def effective_instruction(user_data: Dict[str, Any], kind: str) -> str:
    """The user's saved instructions of ``kind`` (style, structure, search), else the default."""
    custom = (get_custom_instruction(user_data, kind) or "").strip()
    return custom or get_default_instruction(kind)[0]


def initial_session(user_id: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
    """A fresh session as the web app has it after sign-in and ``/api/phases/init/``."""
    return {
        "user": {"id": user_id, "provider": "batch"},
        "cv_text": latest_cv_text(user_data),
        "style_instructions": effective_instruction(user_data, "style"),
        "structure_instructions": effective_instruction(user_data, "structure"),
        "search_instructions": effective_instruction(user_data, "search"),
        "metadata": {"common": {}},
        "vendors": {},
    }


def persistable_state(session: Dict[str, Any]) -> Dict[str, Any]:
    """What goes to ``opportunities/{id}/state/session``."""
    return {k: v for k, v in dict(session).items() if k not in NOT_PERSISTED_KEYS}


VendorFn = Callable[[str, HeadlessSession], None]


def run_vendors_parallel(
    common: Dict[str, Any],
    vendors: Sequence[str],
    fn: VendorFn,
    session_key: str,
    *,
    max_workers: Optional[int] = None,
    on_finished: Optional[Callable[[str, Optional[Dict[str, Any]]], None]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Run ``fn(vendor, session)`` for each vendor in its own thread on its own deep copy of
    ``common``. Returns (``vendors[<vendor>]`` state of each vendor that succeeded, errors).

    ``save_vendor_data`` copy-modify-writes ``session['vendors']``, so sharing one dict between
    threads would lose updates; only each vendor's own entry is merged back, under a lock.
    ``on_finished(vendor, state)`` runs as each vendor ends, with its state or None when it failed
    (progress reports, saving each draft at once); its errors are ignored.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    lock = threading.Lock()

    def one(vendor: str) -> None:
        data = copy.deepcopy(common)
        try:
            with headless_session(data, session_key) as sess:
                fn(vendor, sess)
                state = (sess.get("vendors") or {}).get(vendor)
            if not state:
                raise RuntimeError(f"{vendor} finished without a vendor state")
            with lock:
                merged[vendor] = state
        except Exception as exc:  # one vendor failing never stops the others
            logger.exception("vendor %s failed", vendor)
            with lock:
                errors[vendor] = f"{type(exc).__name__}: {exc}"[:1000]
            state = None
        if on_finished is not None:
            try:
                on_finished(vendor, state)
            except Exception:
                logger.warning("progress report after %s failed", vendor, exc_info=True)

    with ThreadPoolExecutor(max_workers=max_workers or max(1, len(vendors))) as pool:
        list(pool.map(one, list(vendors)))
    return merged, errors


def merge_vendor_states(session: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> None:
    vendors = dict(session.get("vendors") or {})
    vendors.update(states)
    session["vendors"] = vendors


def vendors_in_order(states: Dict[str, Any], order: Sequence[str]) -> List[str]:
    return [v for v in order if v in states] + [v for v in states if v not in order]
