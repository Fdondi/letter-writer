from fastapi import APIRouter, Request, HTTPException, Depends
from starlette.datastructures import UploadFile
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.firestore_store import get_user_data, get_personal_data_document, update_user_data_cache
from letter_writer.instruction_defaults import get_default_instruction
from google.cloud.firestore import DELETE_FIELD
from letter_writer.autocomplete_core import (
    get_autocomplete_plan_role_defaults,
    get_autocomplete_role_defaults,
    normalize_autocomplete_model_key,
    normalize_autocomplete_model_list,
)
from letter_writer.personal_data_sections import (
    get_cv_revisions,
    get_extra_info,
    get_agent_feedback_context,
    get_models,
    get_background_models,
    get_agentic_draft_model,
    get_autocomplete_max_words,
    get_autocomplete_stop_on_period,
    get_autocomplete_models,
    get_autocomplete_ctrl_letter_map,
    get_autocomplete_shift_letter_map,
    get_autocomplete_plan_model,
    unwrap_for_response,
    wrap_new_field,
    wrap_instruction_field,
    get_instruction_baseline_hash,
    get_instruction_baseline_text,
    get_custom_instruction,
    instruction_firestore_keys,
)
from letter_writer.personal_data_sections import get_style_instructions as get_user_style_instructions
from letter_writer.personal_data_sections import get_search_instructions as get_user_search_instructions
from letter_writer.personal_data_sections import get_structure_instructions as get_user_structure_instructions
from letter_writer.cost_tracker import get_all_model_pricing
from letter_writer.language_settings import (
    get_default_languages,
    get_translation_provider,
    normalize_default_languages,
)
from datetime import datetime, timezone

router = APIRouter()

INSTRUCTION_SESSION_KEYS = {
    "style": "style_instructions",
    "structure": "structure_instructions",
    "search": "search_instructions",
}


def _resolve_instruction_payload(kind: str, session: Session, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Effective instructions plus custom/default metadata for merge UI."""
    user_data = user_data or {}
    session_key = INSTRUCTION_SESSION_KEYS[kind]
    default_text, default_hash = get_default_instruction(kind)

    session_custom = (session.get(session_key) or "").strip()
    profile_custom = get_custom_instruction(user_data, kind).strip()
    custom = session_custom or profile_custom or None

    baseline_hash = get_instruction_baseline_hash(user_data, kind) if custom else ""
    baseline_text = get_instruction_baseline_text(user_data, kind) if custom else ""

    effective = custom if custom else default_text
    if custom and baseline_hash:
        upstream_updated = baseline_hash != default_hash
    elif custom:
        # Legacy custom without a stored baseline — prompt review while it differs from default.
        upstream_updated = custom.strip() != default_text.strip()
    else:
        upstream_updated = False

    return {
        "instructions": effective,
        "custom": custom,
        "default": default_text,
        "baseline": baseline_text or None,
        "default_hash": default_hash,
        "baseline_hash": baseline_hash or None,
        "upstream_updated": upstream_updated,
        "is_custom": custom is not None,
    }


def _save_custom_instruction(
    kind: str,
    session: Session,
    user_id: str,
    instructions: str,
    *,
    default_hash: str,
    default_text: str,
) -> Dict[str, Any]:
    session_key = INSTRUCTION_SESSION_KEYS[kind]
    text = instructions if isinstance(instructions, str) else ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="Instructions cannot be empty")

    session[session_key] = text
    now = datetime.utcnow()
    primary_key = instruction_firestore_keys(kind)[0]
    updates: Dict[str, Any] = {
        primary_key: wrap_instruction_field(
            text,
            now,
            default_baseline_hash=default_hash,
            default_baseline_text=default_text,
        ),
        "updated_at": now,
    }
    user_doc_ref = get_personal_data_document(user_id)
    user_doc_ref.set(updates, merge=True)
    update_user_data_cache(user_id, updates)
    return _resolve_instruction_payload(kind, session, get_user_data(user_id, use_cache=True) or {})


def _clear_custom_instruction(kind: str, session: Session, user_id: str) -> Dict[str, Any]:
    session_key = INSTRUCTION_SESSION_KEYS[kind]
    session.pop(session_key, None)
    now = datetime.utcnow()
    delete_updates: Dict[str, Any] = {key: DELETE_FIELD for key in instruction_firestore_keys(kind)}
    delete_updates["updated_at"] = now
    user_doc_ref = get_personal_data_document(user_id)
    user_doc_ref.set(delete_updates, merge=True)
    update_user_data_cache(user_id, delete_updates)
    return _resolve_instruction_payload(kind, session, get_user_data(user_id, use_cache=True) or {})


def _normalize_competence_ratings(raw: Any) -> Dict[str, int]:
    """Normalize incoming competence ratings to {skill: int 1..5}.

    Accepts either:
    - {"Python": 4, ...}
    - {"ratings": {"Python": 4, ...}}  (legacy/nested payloads)
    """
    payload = raw
    if isinstance(payload, dict) and "ratings" in payload and isinstance(payload.get("ratings"), dict):
        payload = payload["ratings"]
    if not isinstance(payload, dict):
        return {}

    normalized: Dict[str, int] = {}
    for skill, value in payload.items():
        key = str(skill or "").strip()
        if not key:
            continue
        if isinstance(value, bool):
            # bool is technically int in Python, but invalid for ratings.
            continue
        if not isinstance(value, (int, float)):
            continue
        n = int(round(float(value)))
        if n < 1:
            n = 1
        elif n > 5:
            n = 5
        normalized[key] = n
    return normalized


def _normalize_extra_info(raw: Any) -> List[Dict[str, Any]]:
    """Validate extra_info array for Firestore: list of dicts with required id."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("extra_info must be a list")
    out: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            raise ValueError("each extra_info item must be an object")
        eid = str(it.get("id") or "").strip()
        if not eid:
            raise ValueError("each extra_info item must have a non-empty id")
        src = str(it.get("source") or "").strip().lower()
        if src and src not in ("feedback", "manual"):
            raise ValueError("extra_info.source must be 'feedback' or 'manual' if set")
        if src == "feedback" and not str(it.get("user_context") or "").strip():
            raise ValueError("extra_info rows from feedback must include non-empty user_context (CV Q&A)")
        lines_raw = it.get("context_lines")
        ctx_lines: List[str] = []
        if isinstance(lines_raw, list):
            ctx_lines = [str(x) for x in lines_raw]
        entry: Dict[str, Any] = {
            "id": eid,
            "source": src or "manual",
            "category": str(it.get("category") or ""),
            "observation": str(it.get("observation") or ""),
            "user_context": str(it.get("user_context") or ""),
            "user_instructions": str(it.get("user_instructions") or "").strip(),
            "context_lines": ctx_lines,
            "manual_text": str(it.get("manual_text") or "").strip(),
        }
        out.append(entry)
    return out


def _normalize_agent_feedback_context(raw: Any) -> List[Dict[str, Any]]:
    """Validate agent_feedback_context for Firestore (feedback Q&A for model prompts, not CV appendix)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("agent_feedback_context must be a list")
    out: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            raise ValueError("each agent_feedback_context item must be an object")
        eid = str(it.get("id") or "").strip()
        if not eid:
            raise ValueError("each agent_feedback_context item must have a non-empty id")
        src = str(it.get("source") or "").strip().lower()
        if src and src != "feedback":
            raise ValueError('agent_feedback_context.source must be "feedback" if set')
        if not str(it.get("user_context") or "").strip():
            raise ValueError("agent_feedback_context rows from feedback must include non-empty user_context")
        out.append(
            {
                "id": eid,
                "source": "feedback",
                "category": str(it.get("category") or ""),
                "user_context": str(it.get("user_context") or ""),
                "user_instructions": str(it.get("user_instructions") or "").strip(),
            }
        )
    return out


def _stamp_agent_feedback_context_items(
    previous: List[Dict[str, Any]],
    normalized_incoming: List[Dict[str, Any]],
    now: datetime,
) -> List[Dict[str, Any]]:
    """Set each row's ``updated_at``: unchanged content keeps the prior timestamp; new/changed rows get *now*."""
    prev_norm_map: Dict[str, Optional[Dict[str, Any]]] = {}
    prev_ts_map: Dict[str, Any] = {}
    for e in previous:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        eid = str(e.get("id") or "").strip()
        if not eid:
            continue
        try:
            prev_norm_map[eid] = _normalize_agent_feedback_context([e])[0]
        except ValueError:
            prev_norm_map[eid] = None
        prev_ts_map[eid] = e.get("updated_at")

    out: List[Dict[str, Any]] = []
    for it in normalized_incoming:
        row = dict(it)
        eid = str(row.get("id") or "").strip()
        old_n = prev_norm_map.get(eid)
        if old_n is not None and old_n == row:
            row["updated_at"] = _coerce_utc_datetime(prev_ts_map.get(eid), now)
        else:
            row["updated_at"] = now
        out.append(row)
    return out


def _coerce_utc_datetime(val: Any, default: datetime) -> datetime:
    if val is None:
        return default
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if hasattr(val, "timestamp"):
        return datetime.fromtimestamp(val.timestamp(), tz=timezone.utc)
    return default


def _stamp_extra_info_items(
    previous: List[Dict[str, Any]],
    normalized_incoming: List[Dict[str, Any]],
    now: datetime,
) -> List[Dict[str, Any]]:
    """Set each row's ``updated_at``: unchanged content keeps the prior timestamp; new/changed rows get *now*."""
    prev_norm_map: Dict[str, Optional[Dict[str, Any]]] = {}
    prev_ts_map: Dict[str, Any] = {}
    for e in previous:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        eid = str(e.get("id") or "").strip()
        if not eid:
            continue
        try:
            prev_norm_map[eid] = _normalize_extra_info([e])[0]
        except ValueError:
            prev_norm_map[eid] = None
        prev_ts_map[eid] = e.get("updated_at")

    out: List[Dict[str, Any]] = []
    for it in normalized_incoming:
        row = dict(it)
        eid = str(row.get("id") or "").strip()
        old_n = prev_norm_map.get(eid)
        if old_n is not None and old_n == row:
            row["updated_at"] = _coerce_utc_datetime(prev_ts_map.get(eid), now)
        else:
            row["updated_at"] = now
        out.append(row)
    return out


def _append_cv_revision(user_id: str, content: str, source: str = "manual_edit") -> None:
    """Append a new CV revision to Firestore and update cache."""
    now = datetime.now(timezone.utc)
    user_data = get_user_data(user_id, use_cache=False) or {}
    revisions = list(get_cv_revisions(user_data))
    revision_number = len(revisions) + 1
    new_revision = {
        "content": content,
        "source": source,
        "created_at": now,  # Firestore stores datetime natively
        "revision_number": revision_number,
    }
    revisions.append(new_revision)
    updates = {
        "cv_revisions": revisions,
        "updated_at": now,
    }
    user_doc_ref = get_personal_data_document(user_id)
    user_doc_ref.set(updates, merge=True)
    update_user_data_cache(user_id, updates)


@router.get("/personal-data/")
async def get_personal_data(session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_id = user['id']
    user_data = get_user_data(user_id, use_cache=True) or {}
    
    # Logic similar to views.py to parse revisions, languages, etc.
    revisions = get_cv_revisions(user_data)
    default_languages = get_default_languages(user_data)
    translation_provider = get_translation_provider(user_data)
    default_models = get_models(user_data)
    default_background_models = get_background_models(user_data)
    agentic_draft_model = get_agentic_draft_model(user_data)
    min_column_width = user_data.get("min_column_width")
    
    # Process revisions to ISO format... (omitted detailed implementation for brevity)
    response_revisions = []
    latest_content = ""
    # ...
    # Simplified for now:
    if revisions:
        latest = revisions[-1] # Simplification
        latest_content = latest.get('content', '')
        response_revisions = revisions

    return {
        "cv": latest_content,
        "revisions": response_revisions,
        "extra_info": get_extra_info(user_data),
        "default_languages": default_languages,
        "translation_provider": translation_provider,
        "default_models": default_models,
        "default_background_models": default_background_models,
        "agentic_draft_model": agentic_draft_model,
        "min_column_width": min_column_width,
        "structure_instructions": get_user_structure_instructions(user_data),
        "autocomplete_max_words": get_autocomplete_max_words(user_data),
        "autocomplete_stop_on_period": get_autocomplete_stop_on_period(user_data),
        "autocomplete_models": get_autocomplete_models(user_data),
        "autocomplete_ctrl_letter_map": get_autocomplete_ctrl_letter_map(user_data),
        "autocomplete_shift_letter_map": get_autocomplete_ctrl_letter_map(user_data),
        "autocomplete_role_defaults": get_autocomplete_role_defaults(),
        "autocomplete_plan_role_defaults": get_autocomplete_plan_role_defaults(),
        "autocomplete_plan_model": get_autocomplete_plan_model(user_data),
    }

@router.post("/personal-data/")
async def update_personal_data(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = user['id']

    # Handle file upload or JSON
    content_type = request.headers.get('content-type', '')
    if 'multipart/form-data' in content_type:
        form = await request.form()
        file = form.get('file')
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
        if not isinstance(file, UploadFile):
            raise HTTPException(status_code=400, detail="Invalid file upload")
        
        MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
        file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
        import re as _re
        raw_filename = file.filename or "upload"
        filename = _re.sub(r"[^\w\s.\-]", "", raw_filename.replace("/", "").replace("\\", ""))[:255] or "upload"
        # For txt/md, decode as text; for PDF we'd need extraction
        extracted_text = file_bytes.decode('utf-8', errors='replace')
        
        # Save to Firestore as new revision
        _append_cv_revision(user_id, extracted_text, source=f"file_upload:{filename}")
        user_data = get_user_data(user_id, use_cache=False) or {}
        revisions = get_cv_revisions(user_data)
        latest_content = revisions[-1].get("content", "") if revisions else ""
        
        return {
            "status": "ok",
            "cv": latest_content,
            "revisions": revisions,
            "extra_info": get_extra_info(user_data),
        }
    else:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        user_doc_ref = get_personal_data_document(user_id)
        updates: Dict[str, Any] = {"updated_at": datetime.utcnow()}
        now = datetime.utcnow()
        
        if "default_languages" in data:
            updates["default_languages"] = normalize_default_languages(data["default_languages"])
        if "translation_provider" in data:
            provider = str(data["translation_provider"] or "google").strip().lower()
            if provider not in ("google", "llm"):
                raise HTTPException(status_code=400, detail="translation_provider must be 'google' or 'llm'")
            updates["translation_provider"] = wrap_new_field("translation_provider", provider, now)
        if "default_models" in data:
            updates["models"] = wrap_new_field("models", data["default_models"], now)
            # Update session
            if "metadata" not in session: session["metadata"] = {}
            if "common" not in session["metadata"]: session["metadata"]["common"] = {}
            session["metadata"]["common"]["selected_vendors"] = data["default_models"]
            
        if "default_background_models" in data:
            requested_models = data["default_background_models"] or []
            searchable_models = get_all_model_pricing(search_only=True)
            allowed_ids = {
                f"{m['vendor_key']}/{m['id']}"
                for models in searchable_models.values()
                for m in models
            }
            valid_models = [mid for mid in requested_models if mid in allowed_ids]
            updates["background_models"] = wrap_new_field("background_models", valid_models, now)

        if "agentic_draft_model" in data:
            val = data["agentic_draft_model"]
            stored = (val or "").strip() if isinstance(val, str) else (str(val).strip() if val is not None else None)
            updates["agentic_draft_model"] = wrap_new_field("agentic_draft_model", stored or None, now)

        if "autocomplete_max_words" in data:
            try:
                n = int(data["autocomplete_max_words"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="autocomplete_max_words must be an integer")
            updates["autocomplete_max_words"] = wrap_new_field(
                "autocomplete_max_words", max(1, min(100, n)), now
            )

        if "autocomplete_stop_on_period" in data:
            updates["autocomplete_stop_on_period"] = wrap_new_field(
                "autocomplete_stop_on_period", bool(data["autocomplete_stop_on_period"]), now
            )

        if "autocomplete_models" in data:
            raw_models = data["autocomplete_models"]
            if not isinstance(raw_models, list):
                raise HTTPException(status_code=400, detail="autocomplete_models must be a list")
            cleaned = normalize_autocomplete_model_list([str(m or "") for m in raw_models])
            updates["autocomplete_models"] = wrap_new_field("autocomplete_models", cleaned, now)

        ctrl_map_key = None
        raw_map = None
        if "autocomplete_ctrl_letter_map" in data:
            ctrl_map_key = "autocomplete_ctrl_letter_map"
            raw_map = data["autocomplete_ctrl_letter_map"]
        elif "autocomplete_shift_letter_map" in data:
            ctrl_map_key = "autocomplete_ctrl_letter_map"
            raw_map = data["autocomplete_shift_letter_map"]
        if ctrl_map_key and raw_map is not None:
            if not isinstance(raw_map, dict):
                raise HTTPException(status_code=400, detail="autocomplete_ctrl_letter_map must be an object")
            from letter_writer.autocomplete_core import normalize_autocomplete_model_key

            cleaned_map: Dict[str, str] = {}
            for letter, model in raw_map.items():
                key = str(letter or "").strip().upper()[:1]
                val = str(model or "").strip()
                if not key or not val:
                    continue
                normalized = normalize_autocomplete_model_key(val)
                if normalized:
                    cleaned_map[key] = normalized
            updates[ctrl_map_key] = wrap_new_field(ctrl_map_key, cleaned_map, now)

        if "autocomplete_plan_model" in data:
            val = data["autocomplete_plan_model"]
            stored = (val or "").strip() if isinstance(val, str) else (str(val).strip() if val is not None else None)
            plan_defaults = get_autocomplete_plan_role_defaults()
            normalized = (
                normalize_autocomplete_model_key(stored, plan_defaults) if stored else None
            )
            updates["autocomplete_plan_model"] = wrap_new_field(
                "autocomplete_plan_model", normalized, now
            )

        if "style_instructions" in data:
            updates["style"] = wrap_new_field("style", data["style_instructions"], now)
            session["style_instructions"] = data["style_instructions"]

        if "structure_instructions" in data and isinstance(data.get("structure_instructions"), str):
            updates["structure"] = wrap_new_field("structure", data["structure_instructions"], now)
            session["structure_instructions"] = data["structure_instructions"]
        
        if "search_instructions" in data:
            updates["search_instructions"] = wrap_new_field("search_instructions", data["search_instructions"], now)
            session["search_instructions"] = data["search_instructions"]
        
        if "competence_ratings" in data:
            normalized_ratings = _normalize_competence_ratings(data["competence_ratings"])
            if normalized_ratings:
                updates["competences"] = wrap_new_field("competences", normalized_ratings, now)

        if "extra_info" in data:
            try:
                normalized_extra = _normalize_extra_info(data["extra_info"])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            user_data_before = get_user_data(user_id, use_cache=False) or {}
            previous_rows = get_extra_info(user_data_before)
            now_ts = datetime.now(timezone.utc)
            updates["extra_info"] = _stamp_extra_info_items(previous_rows, normalized_extra, now_ts)

        if "agent_feedback_context" in data:
            try:
                normalized_agent = _normalize_agent_feedback_context(data["agent_feedback_context"])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            user_data_before = get_user_data(user_id, use_cache=False) or {}
            previous_rows = get_agent_feedback_context(user_data_before)
            now_ts = datetime.now(timezone.utc)
            updates["agent_feedback_context"] = _stamp_agent_feedback_context_items(
                previous_rows, normalized_agent, now_ts
            )
            
        if "content" in data and data["content"]:
            content = str(data["content"]).strip()
            source = str(data.get("source") or "manual_edit").strip() or "manual_edit"
            _append_cv_revision(user_id, content, source=source)
        
        if updates:
            user_doc_ref.set(updates, merge=True)
            update_user_data_cache(user_id, updates)
        
        response: Dict[str, Any] = {"status": "ok"}
        if "content" in data and data["content"]:
            user_data = get_user_data(user_id, use_cache=True) or {}
            revisions = get_cv_revisions(user_data)
            latest = revisions[-1] if revisions else {}
            response["cv"] = latest.get("content", "")
            response["revisions"] = revisions
        if "extra_info" in data:
            user_data = get_user_data(user_id, use_cache=True) or {}
            response["extra_info"] = get_extra_info(user_data)
        return response

@router.get("/instructions-summary/")
async def get_instructions_summary(session: Session = Depends(get_session)):
    """Lightweight upstream-update counts for the AI Instructions entry point."""
    user = session.get("user")
    user_data: Dict[str, Any] = {}
    if user:
        user_data = get_user_data(user["id"], use_cache=False) or {}

    tabs = []
    for kind in INSTRUCTION_SESSION_KEYS:
        payload = _resolve_instruction_payload(kind, session, user_data)
        if payload.get("upstream_updated"):
            tabs.append(kind)
    return {"upstream_updated_tabs": tabs, "has_upstream_update": len(tabs) > 0}


@router.get("/style-instructions/")
async def get_style_instructions_endpoint(session: Session = Depends(get_session)):
    user = session.get("user")
    user_data: Dict[str, Any] = {}
    if user:
        user_data = get_user_data(user["id"], use_cache=False) or {}
    return _resolve_instruction_payload("style", session, user_data)


@router.post("/style-instructions/")
async def update_style_instructions(request: Request, session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    data = await request.json()
    instructions = data.get("instructions", "")
    default_text, default_hash = get_default_instruction("style")
    payload = _save_custom_instruction(
        "style", session, user["id"], instructions, default_hash=default_hash, default_text=default_text
    )
    return {"status": "ok", **payload}


@router.delete("/style-instructions/")
async def clear_style_instructions(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = _clear_custom_instruction("style", session, user["id"])
    return {"status": "ok", **payload}


@router.get("/structure-instructions/")
async def get_structure_instructions_endpoint(session: Session = Depends(get_session)):
    user = session.get("user")
    user_data: Dict[str, Any] = {}
    if user:
        user_data = get_user_data(user["id"], use_cache=False) or {}
    return _resolve_instruction_payload("structure", session, user_data)


@router.post("/structure-instructions/")
async def update_structure_instructions(request: Request, session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    data = await request.json()
    instructions = data.get("instructions", "")
    if not isinstance(instructions, str):
        raise HTTPException(status_code=400, detail="Instructions must be a string")
    default_text, default_hash = get_default_instruction("structure")
    payload = _save_custom_instruction(
        "structure", session, user["id"], instructions, default_hash=default_hash, default_text=default_text
    )
    return {"status": "ok", **payload}


@router.delete("/structure-instructions/")
async def clear_structure_instructions(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = _clear_custom_instruction("structure", session, user["id"])
    return {"status": "ok", **payload}


@router.get("/search-instructions/")
async def get_search_instructions_endpoint(session: Session = Depends(get_session)):
    user = session.get("user")
    user_data: Dict[str, Any] = {}
    if user:
        user_data = get_user_data(user["id"], use_cache=False) or {}
    return _resolve_instruction_payload("search", session, user_data)


@router.post("/search-instructions/")
async def update_search_instructions(request: Request, session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    data = await request.json()
    instructions = data.get("instructions", "")
    default_text, default_hash = get_default_instruction("search")
    payload = _save_custom_instruction(
        "search", session, user["id"], instructions, default_hash=default_hash, default_text=default_text
    )
    return {"status": "ok", **payload}


@router.delete("/search-instructions/")
async def clear_search_instructions(session: Session = Depends(get_session)):
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = _clear_custom_instruction("search", session, user["id"])
    return {"status": "ok", **payload}
