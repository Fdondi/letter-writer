from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from langsmith import traceable
from openai import OpenAI

from .client import get_client
from .clients.base import ModelVendor, ModelSize
from .generation import (
    accuracy_check,
    company_fit_check,
    company_research,
    fancy_letter,
    generate_letter,
    get_search_instructions,
    human_check,
    instruction_check,
    precision_check,
    rewrite_letter,
    user_fit_check,
    extract_job_metadata,
)
from .retrieval import retrieve_similar_job_offers, select_top_documents
from .session_store import get_session as get_session_from_store, save_session
from .firestore_store import get_collection


@dataclass
class PhaseCost:
    """Cost and token tracking for a single phase."""
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    search_queries: int = 0


@dataclass
class VendorPhaseState:
    top_docs: List[dict] = field(default_factory=list)
    company_report: Optional[str] = None
    draft_letter: Optional[str] = None
    final_letter: Optional[str] = None
    feedback: Dict[str, str] = field(default_factory=dict)
    # Legacy aggregate fields (for backward compatibility)
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    # Per-phase cost tracking
    phase_costs: Dict[str, PhaseCost] = field(default_factory=dict)
    
    def add_phase_cost(self, phase: str, cost: float, input_tokens: int, output_tokens: int, search_queries: int = 0):
        """Add cost for a specific phase."""
        if phase not in self.phase_costs:
            self.phase_costs[phase] = PhaseCost()
        self.phase_costs[phase].cost += cost
        self.phase_costs[phase].input_tokens += input_tokens
        self.phase_costs[phase].output_tokens += output_tokens
        self.phase_costs[phase].search_queries += search_queries
        # Also update legacy totals
        self.cost += cost
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


@dataclass
class SessionState:
    session_id: str
    job_text: str
    cv_text: str
    search_result: List[dict]  # Changed from List[ScoredPoint] to List[dict] for Firestore
    style_instructions: str = ""
    vendors: Dict[str, VendorPhaseState] = field(default_factory=dict)
    metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)  # vendor -> extraction
    # vendors_list is deprecated - derive from vendors.keys() or metadata.keys() instead
    vendors_list: List[ModelVendor] = field(default_factory=list)
    
    def get_vendors_with_data(self) -> List[ModelVendor]:
        """Get list of vendors that have data (either in vendors dict or metadata)."""
        vendor_names = set(self.vendors.keys()) | set(self.metadata.keys())
        return [ModelVendor(v) for v in vendor_names if v]


# Keep SESSION_LOCK for thread safety, but sessions are now stored in Firestore
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


def _update_cost(state: VendorPhaseState, client, phase: str = "unknown") -> None:
    """Update state with cost from client, tracking by phase.
    
    Args:
        state: The vendor phase state to update
        client: The AI client with cost/token counters
        phase: The phase name (background, draft, feedback, refine)
    """
    cost = float(getattr(client, "total_cost", 0.0) or 0.0)
    input_tokens = int(getattr(client, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(client, "total_output_tokens", 0) or 0)
    search_queries = int(getattr(client, "total_search_queries", 0) or 0)
    
    print(f"[DEBUG] _update_cost({phase}): cost={cost}, in={input_tokens}, out={output_tokens}, search={search_queries}")
    
    state.add_phase_cost(phase, cost, input_tokens, output_tokens, search_queries)


def _get_client_usage(client) -> tuple:
    """Get current usage from client (cost, input_tokens, output_tokens)."""
    return (
        float(getattr(client, "total_cost", 0.0) or 0.0),
        int(getattr(client, "total_input_tokens", 0) or 0),
        int(getattr(client, "total_output_tokens", 0) or 0),
    )


def _reset_client_counters(client) -> None:
    """Reset client counters after capturing usage."""
    client.total_cost = 0.0
    client.total_input_tokens = 0
    client.total_output_tokens = 0
    if hasattr(client, "total_search_queries"):
        client.total_search_queries = 0


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


@traceable(run_type="chain", name="run_background_phase")
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
    
    # Fail fast: validate critical data before doing any work
    from .generation import MissingCVError
    if cv_text is None or not cv_text or not str(cv_text).strip():
        error_msg = f"CV text is missing or empty in session {session_id} - cannot proceed with background phase"
        import logging
        logger = logging.getLogger(__name__)
        logger.error(error_msg, extra={"session_id": session_id, "vendor": vendor.value, "cv_text": cv_text, "cv_text_type": type(cv_text).__name__})
        raise MissingCVError(error_msg)
    
    # Extract point of contact from metadata (common or vendor-local)
    point_of_contact = None
    common_metadata = metadata.get("common", {})
    if "point_of_contact" in common_metadata and common_metadata["point_of_contact"]:
        point_of_contact = common_metadata["point_of_contact"]
    elif vendor.value in metadata and "point_of_contact" in metadata[vendor.value]:
        point_of_contact = metadata[vendor.value]["point_of_contact"]
    
    # Get search results if not already cached (read-only, don't save)
    if not search_result:
        # Firestore collection connection
        collection = get_collection()
        openai_client = OpenAI()
        search_result = retrieve_similar_job_offers(job_text, collection, openai_client)
        # Note: search_result is not saved here - it should be saved by the "start phases" API call
    
    # Process vendor-specific work
    # Read metadata: check vendor-local first, then common
    # Note: it is allowed to be empty now! In case we know the intermediary but not the real one.
    company_name = get_metadata_field(metadata, vendor, "company_name", "")
    
    # Debug: log metadata and company_name
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"_run_background_phase: vendor={vendor.value}")
    logger.info(f"_run_background_phase: metadata keys: {list(metadata.keys())}")
    logger.info(f"_run_background_phase: metadata['common']: {metadata.get('common', {})}")
    logger.info(f"_run_background_phase: company_name from get_metadata_field: '{company_name}'")
    
    # Get additional company info from metadata (user's extra context about the company)
    additional_company_info = get_metadata_field(metadata, vendor, "additional_company_info", "")
    
    # Get search instructions from session data, falling back to user data or default file
    search_instructions = common_data.get("search_instructions", "")
    if not search_instructions:
        search_instructions = get_search_instructions()  # Default from file

    trace_dir = Path("trace", f"{company_name}.{vendor.value}.background")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)
    print(f"[PHASE] background -> {vendor.value} :: select_top_documents")
    result = select_top_documents(search_result, job_text, ai_client, trace_dir)
    top_docs = result["top_docs"]
    print(f"[PHASE] background -> {vendor.value} :: company_research")
    company_report = company_research(company_name, job_text, ai_client, trace_dir, point_of_contact=point_of_contact, additional_company_info=additional_company_info, search_instructions=search_instructions)

    state = VendorPhaseState(
        top_docs=top_docs,
        company_report=company_report,
    )
    _update_cost(state, ai_client, phase="background")
    
    # Save vendor-specific data (lock-free, atomic)
    from .session_store import save_vendor_data
    save_vendor_data(session_id, vendor.value, state)
    
    return state


@traceable(run_type="chain", name="advance_to_draft")
def advance_to_draft(
    *,
    session_id: str,
    vendor: ModelVendor,
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    style_instructions: str = "",
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
                    state.top_docs = select_top_documents(session.search_result, session.job_text, ai_client, trace_dir)["top_docs"]
                    _update_cost(state, ai_client, phase="background")
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
    job_text = session.job_text
    cv_text = session.cv_text
    
    # Use provided instructions or fall back to session
    if not style_instructions:
        style_instructions = session.style_instructions
    
    # Get additional user info from metadata (user's info relevant to this position, not in CV)
    additional_user_info = get_metadata_field(session.metadata, vendor, "additional_user_info", "")

    state.company_report = company_report
    state.top_docs = top_docs

    try:
        # Reset counters to track draft generation separately
        _reset_client_counters(ai_client)
        
        print(f"[PHASE] draft -> {vendor.value} :: generate_letter (XLARGE)")
        draft_letter = generate_letter(
            cv_text, top_docs, company_report, job_text, ai_client, trace_dir, style_instructions, additional_user_info
        )
        
        # Capture draft cost before feedback generation
        _update_cost(state, ai_client, phase="draft")
        _reset_client_counters(ai_client)
        
        # Run checks on the draft so the user can review/override feedback before refinement
        print(f"[PHASE] draft -> {vendor.value} :: running checks (TINY)")
        with ThreadPoolExecutor(max_workers=5) as executor:
            instruction_future = executor.submit(instruction_check, draft_letter, ai_client, style_instructions)
            accuracy_future = executor.submit(accuracy_check, draft_letter, cv_text, ai_client, additional_user_info)
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
        
        # Capture feedback cost separately
        _update_cost(state, ai_client, phase="feedback")
        
    except Exception:
        traceback.print_exc()
        raise

    state.draft_letter = draft_letter
    state.feedback = feedback
    
    # Save vendor-specific data to session_vendors collection (lock-free)
    from .session_store import save_vendor_data
    save_vendor_data(session.session_id, vendor.value, state)
    
    return state


@traceable(run_type="chain", name="advance_to_refinement")
def advance_to_refinement(
    *,
    session_id: str,
    vendor: ModelVendor,
    draft_override: Optional[str] = None,
    feedback_override: Optional[Dict[str, str]] = None,
    company_report_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
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
    _update_cost(state, ai_client, phase="refine")
    
    # Save vendor-specific data to session_vendors collection (lock-free)
    from .session_store import save_vendor_data
    save_vendor_data(session.session_id, vendor.value, state)
    
    return state


def get_session(session_id: str) -> Optional[SessionState]:
    """Get a session by ID. Loads from MongoDB if not in cache."""
    return get_session_from_store(session_id)

