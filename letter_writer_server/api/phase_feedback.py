from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from letter_writer.firestore_store import save_phase_draft_feedback_snapshot
from letter_writer_server.core.session import Session, get_session

router = APIRouter()


class PhaseFeedbackSnapshotBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    vendor: str = Field(..., min_length=1)
    feedback: Dict[str, Any] = Field(default_factory=dict)
    feedback_overrides: Dict[str, Any] = Field(default_factory=dict)
    document_id: Optional[str] = None


@router.post("/snapshot/")
async def post_phase_feedback_snapshot(
    data: PhaseFeedbackSnapshotBody, session: Session = Depends(get_session)
):
    """Store full draft-phase feedback state (edits, overrides) in ``phase_draft_feedback`` (not RLHF)."""
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = user["id"]
    try:
        doc_id = save_phase_draft_feedback_snapshot(
            user_id=user_id,
            session_id=data.session_id.strip(),
            document_id=(data.document_id or "").strip() or None,
            vendor=data.vendor.strip(),
            feedback=data.feedback,
            feedback_overrides=data.feedback_overrides,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok", "id": doc_id}
