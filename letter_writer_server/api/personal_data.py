from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from letter_writer_server.core.session import Session, get_session
from letter_writer.firestore_store import get_user_data, get_personal_data_document
from letter_writer.generation import get_style_instructions
from letter_writer.personal_data_sections import get_cv_revisions, get_models, unwrap_for_response, wrap_new_field
from datetime import datetime

router = APIRouter()

@router.get("/personal-data")
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
    default_background_models = unwrap_for_response("background_models", user_data.get("background_models")) or []
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
        "min_column_width": min_column_width
    }

@router.post("/personal-data")
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
        filename = file.filename
        # Extract text logic...
        # For now, just save as string
        extracted_text = content.decode('utf-8', errors='replace') # Simplified
        
        # Update Firestore logic...
        # ...
        
        return {"status": "ok", "cv": extracted_text}
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
            updates["background_models"] = wrap_new_field("background_models", data["default_background_models"], now)
            
        if "style_instructions" in data:
            updates["style"] = wrap_new_field("style", data["style_instructions"], now)
            session["style_instructions"] = data["style_instructions"]
            
        if updates:
            user_doc_ref.set(updates, merge=True)
            
        return {"status": "ok"}

@router.get("/style-instructions")
async def get_style_instructions_endpoint(session: Session = Depends(get_session)):
    instructions = session.get("style_instructions", "")
    if not instructions:
        user = session.get('user')
        if user:
             user_data = get_user_data(user['id'], use_cache=True)
             instructions = get_style_instructions(user_data)
    
    if not instructions:
        instructions = get_style_instructions() # Default from file
        
    return {"instructions": instructions}

@router.post("/style-instructions")
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
    
    return {"status": "ok", "instructions": instructions}
