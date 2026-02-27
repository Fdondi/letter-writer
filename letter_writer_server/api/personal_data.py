from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.firestore_store import get_user_data, get_personal_data_document, update_user_data_cache
from letter_writer.generation import get_style_instructions, get_search_instructions
from letter_writer.personal_data_sections import get_cv_revisions, get_models, get_background_models, get_agentic_draft_model, unwrap_for_response, wrap_new_field
from letter_writer.personal_data_sections import get_style_instructions as get_user_style_instructions
from letter_writer.personal_data_sections import get_search_instructions as get_user_search_instructions
from letter_writer.cost_tracker import get_all_model_pricing
from datetime import datetime, timezone

router = APIRouter()


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
    default_languages = user_data.get("default_languages") or []
    default_models = get_models(user_data)
    default_background_models = get_background_models(user_data)
    agentic_draft_model = get_agentic_draft_model(user_data)
    min_column_width = user_data.get("min_column_width")
    
    # Process revisions to ISO format... (omitted detailed implementation for brevity, assume similar to Django view)
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
        "default_languages": default_languages,
        "default_models": default_models,
        "default_background_models": default_background_models,
        "agentic_draft_model": agentic_draft_model,
        "min_column_width": min_column_width
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
        
        content = await file.read()
        filename = file.filename or "upload"
        # For txt/md, decode as text; for PDF we'd need extraction
        extracted_text = content.decode('utf-8', errors='replace')
        
        # Save to Firestore as new revision
        _append_cv_revision(user_id, extracted_text, source=f"file_upload:{filename}")
        user_data = get_user_data(user_id, use_cache=False) or {}
        revisions = get_cv_revisions(user_data)
        latest_content = revisions[-1].get("content", "") if revisions else ""
        
        return {"status": "ok", "cv": latest_content, "revisions": revisions}
    else:
        try:
            data = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        user_doc_ref = get_personal_data_document(user_id)
        updates = {"updated_at": datetime.utcnow()}
        now = datetime.utcnow()
        
        if "default_languages" in data:
            updates["default_languages"] = data["default_languages"]
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
            
        if "style_instructions" in data:
            updates["style"] = wrap_new_field("style", data["style_instructions"], now)
            session["style_instructions"] = data["style_instructions"]
        
        if "search_instructions" in data:
            updates["search_instructions"] = wrap_new_field("search_instructions", data["search_instructions"], now)
            session["search_instructions"] = data["search_instructions"]
        
        if "competence_ratings" in data:
            updates["competences"] = wrap_new_field("competences", data["competence_ratings"], now)
            
        if "content" in data and data["content"]:
            content = str(data["content"]).strip()
            source = str(data.get("source") or "manual_edit").strip() or "manual_edit"
            _append_cv_revision(user_id, content, source=source)
        
        if updates:
            user_doc_ref.set(updates, merge=True)
            update_user_data_cache(user_id, updates)
        
        response = {"status": "ok"}
        if "content" in data and data["content"]:
            user_data = get_user_data(user_id, use_cache=True) or {}
            revisions = get_cv_revisions(user_data)
            latest = revisions[-1] if revisions else {}
            response["cv"] = latest.get("content", "")
            response["revisions"] = revisions
        return response

@router.get("/style-instructions/")
async def get_style_instructions_endpoint(session: Session = Depends(get_session)):
    instructions = session.get("style_instructions", "")
    if not instructions:
        user = session.get('user')
        if user:
             user_data = get_user_data(user['id'], use_cache=False)
             instructions = get_user_style_instructions(user_data or {})
    
    if not instructions:
        instructions = get_style_instructions() # Default from file
        
    return {"instructions": instructions}

@router.post("/style-instructions/")
async def update_style_instructions(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    data = await request.json()
    instructions = data.get("instructions", "")
    if not instructions:
        raise HTTPException(status_code=400, detail="Instructions cannot be empty")
        
    session["style_instructions"] = instructions
    
    # Save to Firestore
    user_doc_ref = get_personal_data_document(user['id'])
    updates = {
        "style": wrap_new_field("style", instructions, datetime.utcnow()),
        "updated_at": datetime.utcnow()
    }
    user_doc_ref.set(updates, merge=True)
    update_user_data_cache(user["id"], updates)

    return {"status": "ok", "instructions": instructions}

@router.get("/search-instructions/")
async def get_search_instructions_endpoint(session: Session = Depends(get_session)):
    instructions = session.get("search_instructions", "")
    if not instructions:
        user = session.get('user')
        if user:
             user_data = get_user_data(user['id'], use_cache=False)
             instructions = get_user_search_instructions(user_data or {})
    
    if not instructions:
        instructions = get_search_instructions() # Default from file
        
    return {"instructions": instructions}

@router.post("/search-instructions/")
async def update_search_instructions(request: Request, session: Session = Depends(get_session)):
    user = session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    data = await request.json()
    instructions = data.get("instructions", "")
    if not instructions:
        raise HTTPException(status_code=400, detail="Instructions cannot be empty")
        
    session["search_instructions"] = instructions
    
    # Save to Firestore
    user_doc_ref = get_personal_data_document(user['id'])
    updates = {
        "search_instructions": wrap_new_field("search_instructions", instructions, datetime.utcnow()),
        "updated_at": datetime.utcnow()
    }
    user_doc_ref.set(updates, merge=True)
    update_user_data_cache(user["id"], updates)

    return {"status": "ok", "instructions": instructions}
