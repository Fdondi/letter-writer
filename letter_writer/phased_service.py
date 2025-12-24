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
    qdrant_host: str
    qdrant_port: int
    search_result: List[ScoredPoint]
    vendors: Dict[str, VendorPhaseState] = field(default_factory=dict)
    metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)  # vendor -> extraction
    vendors_list: List[ModelVendor] = field(default_factory=list)


SESSION_STORE: Dict[str, SessionState] = {}
SESSION_LOCK = Lock()


def _update_cost(state: VendorPhaseState, client) -> None:
    state.cost += float(getattr(client, "total_cost", 0.0) or 0.0)


def _create_session(
    *,
    job_text: str,
    cv_text: str,
    vendors: List[ModelVendor],
    qdrant_host: str,
    qdrant_port: int,
    session_id: str | None = None,
    metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> SessionState:
    session = SessionState(
        session_id=session_id or str(uuid4()),
        job_text=job_text,
        cv_text=cv_text,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        search_result=[],
        metadata=metadata or {},
        vendors_list=vendors,
    )
    SESSION_STORE[session.session_id] = session
    return session


def _run_background_phase(session: SessionState, vendors: List[ModelVendor]) -> SessionState:
    """Run the background phase for the provided vendors using the session context."""
    print(f"[PHASE] background -> start (vendors={','.join(v.value for v in vendors)})")
    qdrant_client = QdrantClient(host=session.qdrant_host, port=session.qdrant_port)
    openai_client = OpenAI()
    session.search_result = retrieve_similar_job_offers(session.job_text, qdrant_client, openai_client)

    def _run_for_vendor(vendor: ModelVendor) -> tuple[str, VendorPhaseState]:
        extraction = session.metadata.get(vendor.value, {})
        company_name = extraction.get("company_name") or ""
        if not company_name:
            raise ValueError(f"company_name is required for vendor {vendor.value} before background")

        trace_dir = Path("trace", f"{company_name}.{vendor.value}.background")
        trace_dir.mkdir(parents=True, exist_ok=True)
        ai_client = get_client(vendor)
        print(f"[PHASE] background -> {vendor.value} :: select_top_documents")
        top_docs = select_top_documents(session.search_result, session.job_text, ai_client, trace_dir)
        print(f"[PHASE] background -> {vendor.value} :: company_research")
        company_report = company_research(company_name, session.job_text, ai_client, trace_dir)

        state = VendorPhaseState(
            top_docs=top_docs,
            company_report=company_report,
        )
        _update_cost(state, ai_client)
        return vendor.value, state

    with ThreadPoolExecutor(max_workers=len(vendors) or 1) as executor:
        for vendor_key, state in executor.map(_run_for_vendor, vendors):
            session.vendors[vendor_key] = state

    SESSION_STORE[session.session_id] = session
    return session


def start_extraction_phase(
    *,
    job_text: str,
    cv_text: str,
    vendors: List[ModelVendor],
    qdrant_host: str,
    qdrant_port: int,
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
        if session_id and session_id in SESSION_STORE:
            session = SESSION_STORE[session_id]
            session.metadata.update(metadata)
            session.vendors_list = list({*session.vendors_list, *vendors})
            session.job_text = job_text
            session.cv_text = cv_text
            SESSION_STORE[session.session_id] = session
            return session

        session = _create_session(
            job_text=job_text,
            cv_text=cv_text,
            vendors=vendors,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            session_id=session_id,
            metadata=metadata,
        )
        return session


def start_background_phase(
    *,
    job_text: str,
    cv_text: str,
    vendors: List[ModelVendor],
    qdrant_host: str,
    qdrant_port: int,
) -> SessionState:
    """Start a phased run directly at background (legacy entrypoint)."""
    metadata = {v.value: {"company_name": ""} for v in vendors}
    session = _create_session(
        job_text=job_text,
        cv_text=cv_text,
        vendors=vendors,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
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
    session = SESSION_STORE.get(session_id)
    if session is None:
        raise ValueError("Invalid session_id")

    if metadata_override:
        for key, val in metadata_override.items():
            if val is None:
                continue
            session.metadata[key] = val

    session.job_text = job_text_override or session.job_text
    session.cv_text = cv_text_override or session.cv_text
    if vendors:
        session.vendors_list = vendors

    target_vendors = session.vendors_list or vendors or []
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
    session = SESSION_STORE.get(session_id)
    if session is None:
        raise ValueError("Invalid session_id")

    state = session.vendors.get(vendor.value)
    if state is None:
        # Vendor might not be in session if background phase failed
        # But if we have metadata for it, recreate the state as if API had succeeded with user's input
        if vendor.value in session.metadata:
            # Recreate state exactly as if API had succeeded but returned user's manual input
            # We still need to run retrieval to get top_docs (unless override provided)
            vendor_metadata = session.metadata.get(vendor.value, {})
            company_name = vendor_metadata.get("company_name") or "Unknown Company"
            
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
            if vendor not in session.vendors_list:
                session.vendors_list.append(vendor)
            SESSION_STORE[session.session_id] = session
        else:
            raise ValueError(f"Vendor {vendor.value} not in session")

    # Get company_name from metadata
    vendor_metadata = session.metadata.get(vendor.value, {})
    company_name = vendor_metadata.get("company_name") or "Unknown Company"
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
    session = SESSION_STORE.get(session_id)
    if session is None:
        raise ValueError("Invalid session_id")

    state = session.vendors.get(vendor.value)
    if state is None:
        raise ValueError(f"Vendor {vendor.value} not in session")

    # Get company_name from metadata
    vendor_metadata = session.metadata.get(vendor.value, {})
    company_name = vendor_metadata.get("company_name") or "Unknown Company"
    trace_dir = Path("trace", f"{company_name}.{vendor.value}.refine")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)

    top_docs = top_docs_override or state.top_docs
    company_report = company_report_override or state.company_report or ""
    job_text = job_text_override or session.job_text
    cv_text = cv_text_override or session.cv_text
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
    return state


def get_session(session_id: str) -> Optional[SessionState]:
    return SESSION_STORE.get(session_id)

