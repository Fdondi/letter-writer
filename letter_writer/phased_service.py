from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import ScoredPoint

from .client import get_client
from .clients.base import ModelVendor, ModelSize
from .generation import (
    accuracy_check,
    company_fit_check,
    company_research,
    fancy_letter,
    generate_letter,
    human_check,
    instruction_check,
    precision_check,
    rewrite_letter,
    user_fit_check,
    extract_job_metadata,
)
from .retrieval import retrieve_similar_job_offers, select_top_documents
from .session_store import get_session as get_session_from_store, save_session


@dataclass
class VendorPhaseState:
    top_docs: List[dict] = field(default_factory=list)
    company_report: Optional[str] = None
    draft_letter: Optional[str] = None
    final_letter: Optional[str] = None
    feedback: Dict[str, str] = field(default_factory=dict)
    cost: float = 0.0


@dataclass
class SessionState:
    session_id: str
    job_text: str
    cv_text: str
    search_result: List[ScoredPoint]
    vendors: Dict[str, VendorPhaseState] = field(default_factory=dict)
    metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)  # vendor -> extraction
    # vendors_list is deprecated - derive from vendors.keys() or metadata.keys() instead
    vendors_list: List[ModelVendor] = field(default_factory=list)
    
    def get_vendors_with_data(self) -> List[ModelVendor]:
        """Get list of vendors that have data (either in vendors dict or metadata)."""
        vendor_names = set(self.vendors.keys()) | set(self.metadata.keys())
        return [ModelVendor(v) for v in vendor_names if v]


# Keep SESSION_LOCK for thread safety, but sessions are now stored in MongoDB
SESSION_LOCK = Lock()


def get_metadata_field(metadata: dict, vendor: ModelVendor, field: str, default: str = ""):
    """Get a metadata field, checking vendor-specific storage first, then common metadata.
    
    This implements the lookup pattern: vendor-local -> common metadata.
    Writing is always vendor-local, reading checks vendor-local first.
    
    Args:
        metadata: The metadata dict (from session.metadata or common_data["metadata"])
        vendor: The vendor to get metadata for
        field: The field name to look up (e.g., "company_name", "job_title")
        default: Default value if field is not found
    
    Returns:
        The field value from vendor-specific metadata, or common metadata, or default
    """
    # First check vendor-specific metadata (if it exists)
    vendor_metadata = metadata.get(vendor.value, {})
    if field in vendor_metadata:
        return vendor_metadata.get(field, default)
    
    # Fall back to common metadata
    common_metadata = metadata.get("common", {})
    return common_metadata.get(field, default)


def set_metadata_field(metadata: dict, vendor: ModelVendor, field: str, value: str):
    """Set a metadata field in vendor-specific storage.
    
    Writing is always vendor-local - vendors never write to common metadata.
    
    Args:
        metadata: The metadata dict (from session.metadata)
        vendor: The vendor to set metadata for
        field: The field name to set (e.g., "company_name", "job_title")
        value: The value to set
    """
    # Ensure vendor-specific metadata dict exists
    if vendor.value not in metadata:
        metadata[vendor.value] = {}
    
    # Write to vendor-specific storage
    metadata[vendor.value][field] = value


def _update_cost(state: VendorPhaseState, client) -> None:
    state.cost += float(getattr(client, "total_cost", 0.0) or 0.0)


def _create_session(
    *,
    job_text: str,
    cv_text: str,
    vendors: List[ModelVendor],
    session_id: str | None = None,
    metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> SessionState:
    session = SessionState(
        session_id=session_id or str(uuid4()),
        job_text=job_text,
        cv_text=cv_text,
        search_result=[],
        metadata=metadata or {},
        vendors_list=vendors,  # Keep for backward compatibility during migration
    )
    save_session(session)
    return session


def _run_background_phase(session_id: str, vendor: ModelVendor, 
                          common_data: dict) -> VendorPhaseState:
    """Run the background phase for a single vendor.
    
    Reads common data, processes vendor-specific work, and saves only vendor data.
    Completely lock-free - vendors work in parallel.
    """
    print(f"[PHASE] background -> start (vendor={vendor.value})")
    
    # Extract common data
    job_text = common_data["job_text"]
    cv_text = common_data["cv_text"]
    metadata = common_data["metadata"]
    search_result = common_data.get("search_result", [])
    
    # Get search results if not already cached (read-only, don't save)
    if not search_result:
        # Qdrant connection is a server-side constant, read from environment
        from .config import env_default
        qdrant_host = env_default("QDRANT_HOST", "localhost")
        qdrant_port = int(env_default("QDRANT_PORT", "6333"))
        qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)
        openai_client = OpenAI()
        search_result = retrieve_similar_job_offers(job_text, qdrant_client, openai_client)
        # Note: search_result is not saved here - it should be saved by the "start phases" API call
    
    # Process vendor-specific work
    # Read metadata: check vendor-local first, then common
    company_name = get_metadata_field(metadata, vendor, "company_name", "")
    if not company_name:
        raise ValueError(f"company_name is required in metadata (vendor-local or common) before background")

    trace_dir = Path("trace", f"{company_name}.{vendor.value}.background")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)
    print(f"[PHASE] background -> {vendor.value} :: select_top_documents")
    top_docs = select_top_documents(search_result, job_text, ai_client, trace_dir)
    print(f"[PHASE] background -> {vendor.value} :: company_research")
    company_report = company_research(company_name, job_text, ai_client, trace_dir)

    state = VendorPhaseState(
        top_docs=top_docs,
        company_report=company_report,
    )
    _update_cost(state, ai_client)
    
    # Save vendor-specific data (lock-free, atomic)
    from .session_store import save_vendor_data
    save_vendor_data(session_id, vendor.value, state)
    
    return state


def start_extraction_phase(
    *,
    job_text: str,
    cv_text: str,
    vendors: List[ModelVendor],
    session_id: str | None = None,
) -> SessionState:
    """First phase: per-vendor extraction of company/job info using each vendor's TINY model."""
    print(f"[PHASE] extraction -> start (vendors={','.join(v.value for v in vendors)})")

    def _extract(vendor: ModelVendor) -> tuple[str, Dict[str, str]]:
        ai_client = get_client(vendor)
        trace_dir = Path("trace", f"extraction.{vendor.value}")
        extraction = extract_job_metadata(job_text, ai_client, trace_dir=trace_dir)
        return vendor.value, extraction

    metadata: Dict[str, Dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=len(vendors) or 1) as executor:
        for vendor_name, extraction in executor.map(_extract, vendors):
            metadata[vendor_name] = extraction

    # Ensure we do not race when multiple vendors reuse the same session_id
    with SESSION_LOCK:
        if session_id:
            session = get_session_from_store(session_id)
            if session is not None:
                session.metadata.update(metadata)
                # Keep vendors_list in sync - derive from actual data
                existing_vendors = set(session.vendors_list)
                new_vendors = set(vendors)
                session.vendors_list = list(existing_vendors | new_vendors)
                session.job_text = job_text
                session.cv_text = cv_text
                save_session(session)
                return session

        session = _create_session(
            job_text=job_text,
            cv_text=cv_text,
            vendors=vendors,
            session_id=session_id,
            metadata=metadata,
        )
        return session


def start_background_phase(
    *,
    job_text: str,
    cv_text: str,
    vendors: List[ModelVendor],
) -> SessionState:
    """Start a phased run directly at background (legacy entrypoint)."""
    metadata = {v.value: {"company_name": ""} for v in vendors}
    session = _create_session(
        job_text=job_text,
        cv_text=cv_text,
        vendors=vendors,
        metadata=metadata,
    )
    return _run_background_phase(session, vendors)


def resume_background_phase(
    *,
    session_id: str,
    metadata_override: Optional[Dict[str, Dict[str, str]]] = None,
    job_text_override: Optional[str] = None,
    cv_text_override: Optional[str] = None,
    vendors: Optional[List[ModelVendor]] = None,
) -> SessionState:
    """Resume or run background after extraction with optional metadata overrides."""
    session = get_session_from_store(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    if metadata_override:
        for key, val in metadata_override.items():
            if val is None:
                continue
            session.metadata[key] = val

    session.job_text = job_text_override or session.job_text
    session.cv_text = cv_text_override or session.cv_text
    
    # Determine which vendors to process:
    # 1. Use explicitly provided vendors
    # 2. Fall back to vendors with metadata (extraction completed)
    # 3. Fall back to vendors_list (for backward compatibility)
    if vendors:
        target_vendors = vendors
    elif session.metadata:
        # Use vendors that have extraction metadata
        target_vendors = [ModelVendor(v) for v in session.metadata.keys()]
    elif session.vendors_list:
        target_vendors = session.vendors_list
    else:
        target_vendors = []
    
    if not target_vendors:
        raise ValueError("No vendors provided for background phase")

    return _run_background_phase(session, target_vendors)


def advance_to_draft(
    *,
    session_id: str,
    vendor: ModelVendor,
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    job_text_override: Optional[str] = None,
    cv_text_override: Optional[str] = None,
) -> VendorPhaseState:
    # Force reload from MongoDB to ensure we have the latest session state
    # This is important because the session might have been updated by background phase
    from .session_store import load_session
    try:
        session = load_session(session_id, force_reload=True)
    except ValueError as e:
        # Re-raise deserialization errors as-is (they're already descriptive)
        raise
    except Exception as e:
        # Wrap other errors
        raise ValueError(f"Failed to load session {session_id}: {e}") from e
    
    if session is None:
        raise ValueError(f"Session {session_id} not found in database")
    
    # Debug: print session state to help diagnose issues
    print(f"[DEBUG] advance_to_draft: session_id={session_id}, vendor={vendor.value}")
    print(f"[DEBUG] session.vendors keys: {list(session.vendors.keys())}")
    print(f"[DEBUG] session.vendors_list: {[v.value for v in session.vendors_list]}")
    print(f"[DEBUG] session.metadata keys: {list(session.metadata.keys())}")

    state = session.vendors.get(vendor.value)
    if state is None:
        # Vendor might not be in session if background phase failed
        # But if we have metadata (vendor-local or common), recreate the state as if API had succeeded with user's input
        # Check if we have any metadata (vendor-local or common)
        has_metadata = (vendor.value in session.metadata and session.metadata[vendor.value]) or "common" in session.metadata
        if has_metadata:
            # Recreate state exactly as if API had succeeded but returned user's manual input
            # We still need to run retrieval to get top_docs (unless override provided)
            company_name = get_metadata_field(session.metadata, vendor, "company_name", "Unknown Company")
            
            state = VendorPhaseState()
            state.company_report = company_report_override or ""
            
            # If top_docs_override provided, use it; otherwise try to get from session.search_result
            if top_docs_override is not None:
                state.top_docs = top_docs_override
            elif hasattr(session, 'search_result') and session.search_result:
                # Run retrieval to get top_docs (as API would have done)
                trace_dir = Path("trace", f"{company_name}.{vendor.value}.background")
                trace_dir.mkdir(parents=True, exist_ok=True)
                ai_client = get_client(vendor)
                try:
                    state.top_docs = select_top_documents(session.search_result, session.job_text, ai_client, trace_dir)
                    _update_cost(state, ai_client)
                except Exception:
                    # If retrieval fails, use empty list (user can proceed with just company_report)
                    state.top_docs = []
                    state.cost = 0.0
            else:
                # No search_result available, use empty list
                state.top_docs = []
                state.cost = 0.0
            
            session.vendors[vendor.value] = state
            # Keep vendors_list in sync for backward compatibility
            if vendor not in session.vendors_list:
                session.vendors_list.append(vendor)
            # Save vendor state to session_vendors collection
            from .session_store import save_vendor_data
            save_vendor_data(session.session_id, vendor.value, state)
            # Save common session data (vendors_list update)
            save_session(session)
        else:
            raise ValueError(f"Vendor {vendor.value} not in session")

    # Get company_name: check vendor-local first, then common
    company_name = get_metadata_field(session.metadata, vendor, "company_name", "Unknown Company")
    trace_dir = Path("trace", f"{company_name}.{vendor.value}.draft")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)

    top_docs = top_docs_override or state.top_docs
    company_report = company_report_override or state.company_report or ""
    job_text = job_text_override or session.job_text
    cv_text = cv_text_override or session.cv_text

    state.company_report = company_report
    state.top_docs = top_docs

    try:
        print(f"[PHASE] draft -> {vendor.value} :: generate_letter (XLARGE)")
        draft_letter = generate_letter(
            cv_text, top_docs, company_report, job_text, ai_client, trace_dir
        )
        # Run checks on the draft so the user can review/override feedback before refinement
        print(f"[PHASE] draft -> {vendor.value} :: running checks (TINY)")
        with ThreadPoolExecutor(max_workers=5) as executor:
            instruction_future = executor.submit(instruction_check, draft_letter, ai_client)
            accuracy_future = executor.submit(accuracy_check, draft_letter, cv_text, ai_client)
            precision_future = executor.submit(
                precision_check, draft_letter, company_report, job_text, ai_client
            )
            company_fit_future = executor.submit(
                company_fit_check, draft_letter, company_report, job_text, ai_client
            )
            user_fit_future = executor.submit(user_fit_check, draft_letter, top_docs, ai_client)
            human_future = executor.submit(human_check, draft_letter, top_docs, ai_client)

        feedback = {
            "instruction": instruction_future.result(),
            "accuracy": accuracy_future.result(),
            "precision": precision_future.result(),
            "company_fit": company_fit_future.result(),
            "user_fit": user_fit_future.result(),
            "human": human_future.result(),
        }
    except Exception:
        traceback.print_exc()
        raise

    state.draft_letter = draft_letter
    state.feedback = feedback
    _update_cost(state, ai_client)
    
    # Save vendor-specific data to session_vendors collection (lock-free)
    from .session_store import save_vendor_data
    save_vendor_data(session.session_id, vendor.value, state)
    
    return state


def advance_to_refinement(
    *,
    session_id: str,
    vendor: ModelVendor,
    draft_override: Optional[str] = None,
    feedback_override: Optional[Dict[str, str]] = None,
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    job_text_override: Optional[str] = None,
    cv_text_override: Optional[str] = None,
    fancy: bool = False,
) -> VendorPhaseState:
    # Force reload from MongoDB to ensure we have the latest session state
    from .session_store import load_session
    try:
        session = load_session(session_id, force_reload=True)
    except ValueError as e:
        # Re-raise deserialization errors as-is (they're already descriptive)
        raise
    except Exception as e:
        # Wrap other errors
        raise ValueError(f"Failed to load session {session_id}: {e}") from e
    
    if session is None:
        raise ValueError(f"Session {session_id} not found in database")

    state = session.vendors.get(vendor.value)
    if state is None:
        raise ValueError(f"Vendor {vendor.value} not in session")

    # Get company_name: check vendor-local first, then common
    company_name = get_metadata_field(session.metadata, vendor, "company_name", "Unknown Company")
    trace_dir = Path("trace", f"{company_name}.{vendor.value}.refine")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)

    top_docs = top_docs_override or state.top_docs
    company_report = company_report_override or state.company_report or ""
    draft_letter = draft_override or state.draft_letter or ""
    if not draft_letter:
        try:
            raise ValueError("Missing draft letter for refinement")
        except Exception:
            traceback.print_exc()
            raise ValueError("Missing draft letter for refinement")

    state.company_report = company_report
    state.top_docs = top_docs
    if feedback_override is not None:
        # Merge/replace cached feedback with user-provided overrides
        state.feedback = feedback_override

    try:
        feedback = state.feedback or {}
        print(f"[PHASE] refine -> {vendor.value} :: rewrite_letter (XLARGE)")
        refined = rewrite_letter(
            draft_letter,
            feedback.get("instruction", ""),
            feedback.get("accuracy", ""),
            feedback.get("precision", ""),
            feedback.get("company_fit", ""),
            feedback.get("user_fit", ""),
            feedback.get("human", ""),
            ai_client,
            trace_dir,
        )

        if fancy:
            print(f"[PHASE] refine -> {vendor.value} :: fancy_letter")
            refined = fancy_letter(refined, ai_client)
    except Exception:
        traceback.print_exc()
        raise

    state.draft_letter = draft_letter
    state.final_letter = refined
    state.feedback = feedback
    _update_cost(state, ai_client)
    
    # Save vendor-specific data to session_vendors collection (lock-free)
    from .session_store import save_vendor_data
    save_vendor_data(session.session_id, vendor.value, state)
    
    return state


def get_session(session_id: str) -> Optional[SessionState]:
    """Get a session by ID. Loads from MongoDB if not in cache."""
    return get_session_from_store(session_id)

