from __future__ import annotations
import logging
import re
import uuid
from typing import Dict, Optional, TYPE_CHECKING, Any, List, Tuple, cast, Set
from threading import local, Lock
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Thread-local storage for Request (FastAPI)
_thread_local = local()

# In-memory cache (kept for compatibility with existing code structure, though session middleware handles caching)
SESSION_CACHE: Dict[str, Any] = {}
CACHE_LOCK = Lock()
APPLICATION_EVENT_LOG_KEY = "application_event_log"
PENDING_APPLICATION_EVENT_LOG_KEY = "pending_application_event_log"
APPLICATION_LOG_BLOB_STORE_KEY = "pending_application_log_blob_store"
# Firestore document id for which new audit rows are attributed (HTTP session may span many docs).
EVENT_LOG_FIRESTORE_DOCUMENT_ID_KEY = "event_log_firestore_document_id"
# Stored on each event so pending rows can be flushed only with the matching document save.
EVENT_LOG_DOCUMENT_FIELD = "_lw_firestore_document_id"

# Event log pipeline (two phases):
# 1) On append: externalize strings matching known session / payload patterns into a
#    session-scoped blob store; events hold {_lw_log_blob: id} or [[LW_BLOB_REF:uuid]] tokens.
# 2) On document save: resolve blobs against the merged Firestore document snapshot —
#    duplicates become {_lw_doc_ref: "job_text"} or [[LW_DOC_REF:path]]; unique text is inlined.
_MIN_REDACTION_CHARS = 80
LOG_BLOB_LEAF_KEY = "_lw_log_blob"
DOC_REF_LEAF_KEY = "_lw_doc_ref"
BLOB_TOKEN_RE = re.compile(r"\[\[LW_BLOB_REF:([0-9a-f\-]{36})\]\]")
_PERSISTED_TEXT_KEYS = frozenset(
    {
        "job_text",
        "cv_text",
        "company_report",
        "letter_plan",
        "draft_letter",
        "final_letter",
        "style_instructions",
        "structure_instructions",
        "letter_text",
    }
)


def set_event_log_firestore_document_id(document_id: Optional[str]) -> None:
    """Bind new application_event_log rows to a Firestore document (or None for a new unsaved row)."""
    session = _get_session()
    if not session:
        return
    if document_id is None:
        session.pop(EVENT_LOG_FIRESTORE_DOCUMENT_ID_KEY, None)
    else:
        session[EVENT_LOG_FIRESTORE_DOCUMENT_ID_KEY] = str(document_id)


def _collect_blob_ids_in_object(obj: Any, acc: Set[str]) -> None:
    if isinstance(obj, dict):
        if set(obj.keys()) == {LOG_BLOB_LEAF_KEY}:
            bid = obj.get(LOG_BLOB_LEAF_KEY)
            if isinstance(bid, str):
                acc.add(bid)
        else:
            for v in obj.values():
                _collect_blob_ids_in_object(v, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_blob_ids_in_object(item, acc)
    elif isinstance(obj, str):
        for m in BLOB_TOKEN_RE.finditer(obj):
            acc.add(m.group(1))


def _event_matches_firestore_flush(ev: Any, for_firestore_document_id: Optional[str]) -> bool:
    if not isinstance(ev, dict):
        return False
    ev_doc = ev.get(EVENT_LOG_DOCUMENT_FIELD)
    if for_firestore_document_id is None:
        return ev_doc is None
    return ev_doc == for_firestore_document_id


if TYPE_CHECKING:
    from fastapi import Request
    from letter_writer_server.core.session import Session
    from .phased_service import SessionState, VendorPhaseState

def set_current_request(request: Request):
    """Set current FastAPI request in thread-local storage."""
    _thread_local.request = request

def _get_current_request() -> Optional[Request]:
    """Get current FastAPI request from thread-local storage."""
    return getattr(_thread_local, 'request', None)

def _get_session() -> Optional[Session]:
    """Get the custom Session object from the current request."""
    request = _get_current_request()
    if request and hasattr(request.state, 'session'):
        return request.state.session
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _session_canonical_blobs(session: Any) -> List[Tuple[str, str]]:
    """(label, text) pairs for content persisted on the session (or per-vendor state)."""
    pairs: List[Tuple[str, str]] = []

    def add(label: str, value: Any) -> None:
        if not isinstance(value, str):
            return
        if len(value.strip()) < _MIN_REDACTION_CHARS:
            return
        pairs.append((label, value))

    add("job_text", session.get("job_text") or "")
    add("cv_text", session.get("cv_text") or "")
    add("style_instructions", session.get("style_instructions") or "")
    add("structure_instructions", session.get("structure_instructions") or "")

    vendors = session.get("vendors") or {}
    if isinstance(vendors, dict):
        for vname, vdata in vendors.items():
            if not isinstance(vdata, dict):
                continue
            prefix = f"vendors.{vname}"
            add(f"{prefix}.company_report", vdata.get("company_report") or "")
            add(f"{prefix}.letter_plan", vdata.get("letter_plan") or "")
            add(f"{prefix}.draft_letter", vdata.get("draft_letter") or "")
            add(f"{prefix}.final_letter", vdata.get("final_letter") or "")

    return pairs


def _harvest_persisted_blobs_from_event(obj: Any, acc: Dict[str, str]) -> None:
    """Collect large strings under keys that mirror persisted session / document fields.

    ``acc`` maps blob text -> placeholder label (first key wins for duplicate content).
    """
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in _PERSISTED_TEXT_KEYS and isinstance(val, str) and len(val.strip()) >= _MIN_REDACTION_CHARS:
                acc.setdefault(val, str(key))
            # Normalized document field: ai_letters[].text
            if (
                key == "text"
                and isinstance(val, str)
                and len(val.strip()) >= _MIN_REDACTION_CHARS
                and "vendor" in obj
            ):
                acc.setdefault(val, "ai_letters.text")
            _harvest_persisted_blobs_from_event(val, acc)
    elif isinstance(obj, list):
        for item in obj:
            _harvest_persisted_blobs_from_event(item, acc)


def _merge_phase1_catalog(session: Any, event_dict: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Ordered (label, blob) with longest blobs first for safe substring replacement."""
    by_blob: Dict[str, str] = {}
    for label, blob in _session_canonical_blobs(session):
        by_blob.setdefault(blob, label)
    harvested: Dict[str, str] = {}
    _harvest_persisted_blobs_from_event(event_dict, harvested)
    for blob, label in harvested.items():
        by_blob.setdefault(blob, label)
    ordered = sorted(by_blob.items(), key=lambda item: len(item[0]), reverse=True)
    return [(label, blob) for blob, label in ordered]


def _new_blob_id() -> str:
    return str(uuid.uuid4())


def _blob_store_ensure_id(blob_store: Dict[str, Any], text: str, pattern_hint: str) -> str:
    for bid, meta in blob_store.items():
        if isinstance(meta, dict) and meta.get("text") == text:
            return str(bid)
    bid = _new_blob_id()
    blob_store[str(bid)] = {"text": text, "pattern_hint": pattern_hint}
    return str(bid)


def _blob_token(blob_id: str) -> str:
    return f"[[LW_BLOB_REF:{blob_id}]]"


def _phase1_externalize_string(
    s: str, catalog: List[Tuple[str, str]], blob_store: Dict[str, Any]
) -> Any:
    if not isinstance(s, str):
        return s
    for label, blob in catalog:
        if len(blob) < _MIN_REDACTION_CHARS:
            continue
        if s == blob:
            bid = _blob_store_ensure_id(blob_store, blob, label)
            return {LOG_BLOB_LEAF_KEY: bid}
    out = s
    for label, blob in catalog:
        if len(blob) < _MIN_REDACTION_CHARS:
            continue
        if blob in out:
            bid = _blob_store_ensure_id(blob_store, blob, label)
            out = out.replace(blob, _blob_token(bid))
    return out


def _phase1_externalize_tree(obj: Any, catalog: List[Tuple[str, str]], blob_store: Dict[str, Any]) -> Any:
    if isinstance(obj, dict):
        return {str(k): _phase1_externalize_tree(v, catalog, blob_store) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_phase1_externalize_tree(v, catalog, blob_store) for v in obj]
    if isinstance(obj, str):
        return _phase1_externalize_string(obj, catalog, blob_store)
    return obj


def merged_document_snapshot_for_log(
    existing_document: Optional[Dict[str, Any]],
    incoming_fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Shallow merge of existing Firestore doc + incoming write payload for log dedupe."""
    out: Dict[str, Any] = {**(existing_document or {})}
    skip = frozenset({"application_event_log", "vector"})
    for k, v in (incoming_fields or {}).items():
        if k in skip:
            continue
        out[k] = v
    out["job_text"] = (out.get("job_text") or "").strip()
    out["letter_text"] = (out.get("letter_text") or "").strip()
    nlt = out.get("negative_letter_text")
    if isinstance(nlt, str):
        stripped = nlt.strip()
        out["negative_letter_text"] = stripped or None
    return out


def _build_doc_text_paths(doc: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(dotted_path, text) pairs, longest text first for substring token resolution."""
    paths: List[Tuple[str, str]] = []

    def add(path: str, text: Any) -> None:
        if isinstance(text, str) and len(text.strip()) >= _MIN_REDACTION_CHARS:
            paths.append((path, text))

    add("job_text", doc.get("job_text"))
    add("letter_text", doc.get("letter_text"))
    add("negative_letter_text", doc.get("negative_letter_text"))
    add("notes", doc.get("notes"))
    letters = doc.get("ai_letters") or []
    if isinstance(letters, list):
        for i, entry in enumerate(letters):
            if isinstance(entry, dict):
                add(f"ai_letters.{i}.text", entry.get("text"))
    return sorted(paths, key=lambda item: len(item[1]), reverse=True)


def _doc_path_for_exact_text(text: str, sorted_paths: List[Tuple[str, str]]) -> Optional[str]:
    for path, doc_text in sorted_paths:
        if text == doc_text:
            return path
    return None


def _phase2_resolve_string_tokens(
    s: str, blob_store: Dict[str, Any], sorted_paths: List[Tuple[str, str]]
) -> str:
    out_chunks: List[str] = []
    pos = 0
    for m in BLOB_TOKEN_RE.finditer(s):
        out_chunks.append(s[pos : m.start()])
        bid = m.group(1)
        meta = blob_store.get(bid)
        if not isinstance(meta, dict):
            out_chunks.append(m.group(0))
        else:
            t = meta.get("text") or ""
            path = _doc_path_for_exact_text(t, sorted_paths)
            if path:
                out_chunks.append(f"[[LW_DOC_REF:{path}]]")
            else:
                out_chunks.append(t)
        pos = m.end()
    out_chunks.append(s[pos:])
    return "".join(out_chunks)


def _phase2_resolve_leaf_log_blob(
    blob_id: str, blob_store: Dict[str, Any], sorted_paths: List[Tuple[str, str]]
) -> Any:
    meta = blob_store.get(blob_id)
    if not isinstance(meta, dict):
        return {LOG_BLOB_LEAF_KEY: blob_id, "_lw_unresolved": True}
    t = meta.get("text") or ""
    path = _doc_path_for_exact_text(t, sorted_paths)
    if path:
        return {DOC_REF_LEAF_KEY: path}
    return t


def _phase2_resolve_tree(obj: Any, blob_store: Dict[str, Any], sorted_paths: List[Tuple[str, str]]) -> Any:
    if isinstance(obj, dict) and set(obj.keys()) == {LOG_BLOB_LEAF_KEY}:
        bid = obj[LOG_BLOB_LEAF_KEY]
        if isinstance(bid, str):
            return _phase2_resolve_leaf_log_blob(bid, blob_store, sorted_paths)
        return obj
    if isinstance(obj, dict):
        return {str(k): _phase2_resolve_tree(v, blob_store, sorted_paths) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_phase2_resolve_tree(v, blob_store, sorted_paths) for v in obj]
    if isinstance(obj, str):
        return _phase2_resolve_string_tokens(obj, blob_store, sorted_paths)
    return obj


def finalize_application_event_log_for_document(
    events: List[Dict[str, Any]],
    blob_store: Dict[str, Any],
    merged_document: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Resolve phase-1 blob placeholders using the document about to be persisted."""
    from letter_writer.firestore_store import firestore_safe_for_write

    sorted_paths = _build_doc_text_paths(merged_document or {})
    store = dict(blob_store or {})
    out: List[Dict[str, Any]] = []
    for e in events:
        resolved = _phase2_resolve_tree(e, store, sorted_paths)
        if isinstance(resolved, dict):
            resolved.pop(EVENT_LOG_DOCUMENT_FIELD, None)
        out.append(resolved)
    return firestore_safe_for_write(out)


def append_application_event(event: Dict[str, Any]) -> None:
    """Append event to request session cache and pending-save queue."""
    session = _get_session()
    if not session:
        return
    safe_event = _json_safe(event)
    if isinstance(safe_event, dict) and "timestamp" not in safe_event:
        safe_event["timestamp"] = datetime.now(timezone.utc).isoformat()

    if isinstance(safe_event, dict):
        if EVENT_LOG_DOCUMENT_FIELD not in safe_event:
            doc_scope = session.get(EVENT_LOG_FIRESTORE_DOCUMENT_ID_KEY)
            if doc_scope is not None:
                safe_event[EVENT_LOG_DOCUMENT_FIELD] = str(doc_scope)
            else:
                safe_event[EVENT_LOG_DOCUMENT_FIELD] = None
        catalog = _merge_phase1_catalog(session, safe_event)
        blob_store: Dict[str, Any] = session.setdefault(APPLICATION_LOG_BLOB_STORE_KEY, {})
        safe_event = _phase1_externalize_tree(safe_event, catalog, blob_store)

    current_full = session.get(APPLICATION_EVENT_LOG_KEY, [])
    full_list = list(current_full) if isinstance(current_full, list) else []
    full_list.append(safe_event)
    session[APPLICATION_EVENT_LOG_KEY] = full_list

    current_pending = session.get(PENDING_APPLICATION_EVENT_LOG_KEY, [])
    pending_list = list(current_pending) if isinstance(current_pending, list) else []
    pending_list.append(safe_event)
    session[PENDING_APPLICATION_EVENT_LOG_KEY] = pending_list


def consume_pending_application_events(
    for_firestore_document_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return pending events for this Firestore document save and remove them from the session.

    Events are partitioned by ``_lw_firestore_document_id`` so one HTTP session cannot flush
    unrelated phase/LLM history onto the wrong document row.

    ``for_firestore_document_id``:
    - ``None`` (create): only events scoped to ``None`` (unsaved / new row).
    - non-``None`` (update): only events whose scope equals this id.
    """
    session = _get_session()
    if not session:
        return [], {}
    pending = session.get(PENDING_APPLICATION_EVENT_LOG_KEY, [])
    pending_list: List[Dict[str, Any]] = list(pending) if isinstance(pending, list) else []

    matching: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    skipped_unscoped_on_update = 0
    for ev in pending_list:
        if _event_matches_firestore_flush(ev, for_firestore_document_id):
            matching.append(ev)
        else:
            kept.append(ev)
            if for_firestore_document_id is not None and isinstance(ev, dict):
                if ev.get(EVENT_LOG_DOCUMENT_FIELD) is None:
                    skipped_unscoped_on_update += 1

    session[PENDING_APPLICATION_EVENT_LOG_KEY] = kept

    if isinstance(session.get(APPLICATION_EVENT_LOG_KEY), list) and matching:
        match_ids = {id(x) for x in matching}
        full = session.get(APPLICATION_EVENT_LOG_KEY, [])
        session[APPLICATION_EVENT_LOG_KEY] = [x for x in full if id(x) not in match_ids]

    raw_blobs = session.get(APPLICATION_LOG_BLOB_STORE_KEY, {})
    blob_store: Dict[str, Any] = dict(raw_blobs) if isinstance(raw_blobs, dict) else {}

    ids_in_matching: Set[str] = set()
    for ev in matching:
        _collect_blob_ids_in_object(ev, ids_in_matching)
    ids_in_kept: Set[str] = set()
    for ev in kept:
        _collect_blob_ids_in_object(ev, ids_in_kept)

    blob_snap: Dict[str, Any] = {}
    for bid in ids_in_matching:
        meta = blob_store.get(bid)
        if isinstance(meta, dict):
            blob_snap[str(bid)] = meta

    for bid in ids_in_matching:
        if bid not in ids_in_kept:
            blob_store.pop(bid, None)
    session[APPLICATION_LOG_BLOB_STORE_KEY] = blob_store

    if for_firestore_document_id is not None and skipped_unscoped_on_update:
        logger.warning(
            "application_event_log: skipped %s pending events without %s while saving document %s; "
            "load the document (GET) before recording phase work, or they remain queued until a matching save.",
            skipped_unscoped_on_update,
            EVENT_LOG_DOCUMENT_FIELD,
            for_firestore_document_id,
        )

    return matching, blob_snap


def log_user_input_event(source: str, payload: Any) -> None:
    append_application_event(
        {
            "type": "user_input",
            "source": source,
            "payload": _json_safe(payload),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

def check_session_exists(session_id: str) -> bool:
    """Check if a session exists."""
    session = _get_session()
    # In the new system, if we have a session object, it exists.
    # We might want to check if it has any data to be sure it's a valid session
    return bool(session and (session.get('job_text') or session.get('vendors')))

def save_session_common_data(session_id: str, job_text: str, cv_text: str,
                             metadata: dict, search_result: list = None, style_instructions: str = "", structure_instructions: str = "", selected_top_docs: Optional[list] = None, collection=None) -> None:
    session = _get_session()
    if not session:
        return 
    
    session['job_text'] = job_text
    session['cv_text'] = cv_text
    session['style_instructions'] = style_instructions
    if structure_instructions is not None:
        session['structure_instructions'] = structure_instructions
    if search_result is not None:
        session['search_result'] = search_result
    if selected_top_docs is not None:
        session["selected_top_docs"] = list(selected_top_docs)
    
    # Merge metadata
    current_meta = session.get('metadata', {})
    if isinstance(current_meta, dict):
        # We need to be careful not to overwrite existing keys if we want merge behavior
        # But here we are passed 'metadata' which might be the full metadata or update
        # The original implementation merged at field level
        merged = current_meta.copy()
        merged.update(metadata)
        session['metadata'] = merged
    else:
        session['metadata'] = metadata
        
    session['updated_at'] = datetime.utcnow().isoformat()
    if 'created_at' not in session:
        session['created_at'] = datetime.utcnow().isoformat()

def load_session_common_data(session_id: str, collection=None):
    session = _get_session()
    if not session:
        return None
    
    # If session is empty but we have a session object (new session), return defaults
    return {
        "session_id": session_id,
        "job_text": session.get("job_text", ""),
        "cv_text": session.get("cv_text", ""),
        "style_instructions": session.get("style_instructions", ""),
        "structure_instructions": session.get("structure_instructions", ""),
        "search_result": session.get("search_result", []),
        "selected_top_docs": session.get("selected_top_docs", []),
        "metadata": session.get("metadata", {}),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }

def _serialize_vendor_state(state) -> dict:
    """Serialize VendorPhaseState to a dict."""
    return {
        "top_docs": state.top_docs,
        "company_report": state.company_report,
        "letter_plan": state.letter_plan,
        "draft_letter": state.draft_letter,
        "final_letter": state.final_letter,
        "feedback": state.feedback,
        "cost": state.cost,
        # We should also serialize phase_costs if present, but for now basic fields
    }

def _deserialize_vendor_state(data: dict):
    """Deserialize a dict to VendorPhaseState."""
    from .phased_service import VendorPhaseState
    
    # Handle both old and new format if needed
    return VendorPhaseState(
        top_docs=data.get("top_docs", []),
        company_report=data.get("company_report"),
        letter_plan=data.get("letter_plan"),
        draft_letter=data.get("draft_letter"),
        final_letter=data.get("final_letter"),
        feedback=data.get("feedback", {}),
        cost=float(data.get("cost", 0.0)),
    )

def save_vendor_data(session_id: str, vendor: str, vendor_state, collection=None) -> None:
    session = _get_session()
    if not session:
        return

    state_dict = _serialize_vendor_state(vendor_state)
    
    vendors = session.get('vendors', {})
    if not isinstance(vendors, dict):
        vendors = {}
    
    # We need to copy to ensure change detection works if it's a nested dict
    vendors = vendors.copy()
    vendors[vendor] = state_dict
    session['vendors'] = vendors

def load_all_vendor_data(session_id: str, collection=None):
    session = _get_session()
    if not session:
        return {}
    
    return session.get('vendors', {})

def load_vendor_data(session_id: str, vendor: str, collection=None):
    vendors = load_all_vendor_data(session_id, collection)
    data = vendors.get(vendor)
    if data:
        return _deserialize_vendor_state(data)
    return None

def load_session(session_id: str, collection=None, force_reload: bool = False):
    session = _get_session()
    if not session:
        return None
    
    # Construct SessionState
    from .phased_service import SessionState
    from .typed_shapes import TopDocument

    vendors_data = session.get('vendors', {})
    vendors = {}
    for v_name, v_data in vendors_data.items():
        if v_data:
            vendors[v_name] = _deserialize_vendor_state(v_data)

    # Helper for timestamp conversion
    def parse_dt(dt_str):
        if isinstance(dt_str, str):
            try:
                return datetime.fromisoformat(dt_str)
            except ValueError:
                return None
        return dt_str

    # vendors_list deprecated but we can populate it from keys
    from .clients.base import ModelVendor
    vendors_list = []
    for v in vendors.keys():
        try:
            vendors_list.append(ModelVendor(v))
        except ValueError:
            pass

    return SessionState(
        session_id=session_id,
        job_text=session.get("job_text", ""),
        cv_text=session.get("cv_text", ""),
        style_instructions=session.get("style_instructions", ""),
        structure_instructions=session.get("structure_instructions", ""),
        search_result=session.get("search_result", []),
        selected_top_docs=cast(List[TopDocument], list(session.get("selected_top_docs", []) or [])),
        metadata=session.get("metadata", {}),
        vendors=vendors,
        vendors_list=vendors_list
    )

def save_session(session_state, collection=None) -> None:
    # Save everything back to session
    save_session_common_data(
        session_state.session_id,
        session_state.job_text,
        session_state.cv_text,
        session_state.metadata,
        session_state.search_result,
        session_state.style_instructions,
        session_state.structure_instructions,
        session_state.selected_top_docs,
    )
    
    for v_name, v_state in session_state.vendors.items():
        save_vendor_data(session_state.session_id, v_name, v_state)

def get_session(session_id: str, collection=None):
    return load_session(session_id, collection)

def delete_session(session_id: str, collection=None) -> None:
    session = _get_session()
    if session:
        session.clear()

def clear_cache() -> None:
    pass # No-op
