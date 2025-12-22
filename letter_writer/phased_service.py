from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

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
)
from .retrieval import retrieve_similar_job_offers, select_top_documents


@dataclass
class VendorPhaseState:
    top_docs: List[dict] = field(default_factory=list)
    company_report: Optional[str] = None
    background_summary: Optional[str] = None
    main_points: List[str] = field(default_factory=list)
    draft_letter: Optional[str] = None
    final_letter: Optional[str] = None
    feedback: Dict[str, str] = field(default_factory=dict)
    cost: float = 0.0


@dataclass
class SessionState:
    session_id: str
    job_text: str
    cv_text: str
    company_name: str
    qdrant_host: str
    qdrant_port: int
    search_result: List[ScoredPoint]
    vendors: Dict[str, VendorPhaseState] = field(default_factory=dict)


SESSION_STORE: Dict[str, SessionState] = {}


def _strip_code_fence(payload: str) -> str:
    if payload.startswith("```json"):
        payload = payload[len("```json") :]
    if payload.startswith("```"):
        payload = payload[len("```") :]
    if payload.endswith("```"):
        payload = payload[: -len("```")]
    return payload.strip()


def _summarize_background(
    job_text: str,
    top_docs: List[dict],
    company_report: str,
    client,
    trace_dir: Path,
    vendor_name: str,
) -> Tuple[str, List[str]]:
    """Summarize the background research into a short memo and bullet points."""
    docs_preview = "\n\n".join(
        f"- {doc.get('company_name')}: score {doc.get('score')}/10\n{doc.get('job_text','')[:500]}"
        for doc in top_docs
    )
    system = (
        "You are preparing a brief background memo for a cover-letter writer.\n"
        "Given the target job description, the retrieved similar roles, and a company research note, "
        "produce a concise summary and 3-6 main bullet points. "
        "Return JSON with keys `summary` (string) and `main_points` (array of strings)."
    )
    prompt = (
        f"Target job description:\n{job_text}\n\n"
        f"Retrieved roles:\n{docs_preview}\n\n"
        f"Company research:\n{company_report}"
    )
    print(f"[PHASE] background -> {vendor_name} :: summarize (BASE)")
    raw = client.call(ModelSize.BASE, system, [prompt])
    cleaned = _strip_code_fence(raw)

    summary = cleaned
    points: List[str] = []
    try:
        parsed = json.loads(cleaned)
        summary = parsed.get("summary", summary)
        points = parsed.get("main_points", []) or []
    except Exception:
        pass

    (trace_dir / "background_summary.txt").write_text(summary, encoding="utf-8")
    if points:
        (trace_dir / "background_main_points.json").write_text(
            json.dumps(points, indent=2), encoding="utf-8"
        )
    return summary, points


def _update_cost(state: VendorPhaseState, client) -> None:
    state.cost += float(getattr(client, "total_cost", 0.0) or 0.0)


def start_background_phase(
    *,
    job_text: str,
    cv_text: str,
    company_name: str,
    vendors: List[ModelVendor],
    qdrant_host: str,
    qdrant_port: int,
) -> SessionState:
    """Start a phased run: perform background search only."""
    print(f"[PHASE] background -> start (vendors={','.join(v.value for v in vendors)})")
    qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)
    openai_client = OpenAI()
    search_result = retrieve_similar_job_offers(job_text, qdrant_client, openai_client)

    session_id = str(uuid4())
    session = SessionState(
        session_id=session_id,
        job_text=job_text,
        cv_text=cv_text,
        company_name=company_name,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        search_result=search_result,
    )

    for vendor in vendors:
        trace_dir = Path("trace", f"{company_name}.{vendor.value}.background")
        trace_dir.mkdir(parents=True, exist_ok=True)
        ai_client = get_client(vendor)
        try:
            print(f"[PHASE] background -> {vendor.value} :: select_top_documents")
            top_docs = select_top_documents(search_result, job_text, ai_client, trace_dir)
            print(f"[PHASE] background -> {vendor.value} :: company_research")
            company_report = company_research(company_name, job_text, ai_client, trace_dir)
            summary, main_points = _summarize_background(
                job_text, top_docs, company_report, ai_client, trace_dir, vendor.value
            )
        except Exception:
            traceback.print_exc()
            raise

        state = VendorPhaseState(
            top_docs=top_docs,
            company_report=company_report,
            background_summary=summary,
            main_points=main_points,
        )
        _update_cost(state, ai_client)
        session.vendors[vendor.value] = state

    SESSION_STORE[session_id] = session
    return session


def advance_to_draft(
    *,
    session_id: str,
    vendor: ModelVendor,
    company_report_override: Optional[str] = None,
    background_summary_override: Optional[str] = None,
    top_docs_override: Optional[List[dict]] = None,
    job_text_override: Optional[str] = None,
    cv_text_override: Optional[str] = None,
) -> VendorPhaseState:
    session = SESSION_STORE.get(session_id)
    if session is None:
        raise ValueError("Invalid session_id")

    state = session.vendors.get(vendor.value)
    if state is None:
        raise ValueError(f"Vendor {vendor.value} not in session")

    trace_dir = Path("trace", f"{session.company_name}.{vendor.value}.draft")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)

    top_docs = top_docs_override or state.top_docs
    company_report = company_report_override or state.company_report or ""
    job_text = job_text_override or session.job_text
    cv_text = cv_text_override or session.cv_text

    state.background_summary = background_summary_override or state.background_summary
    state.company_report = company_report
    state.top_docs = top_docs

    try:
        print(f"[PHASE] draft -> {vendor.value} :: generate_letter (XLARGE)")
        draft_letter = generate_letter(
            cv_text, top_docs, company_report, job_text, ai_client, trace_dir
        )
    except Exception:
        traceback.print_exc()
        raise

    state.draft_letter = draft_letter
    _update_cost(state, ai_client)
    return state


def advance_to_refinement(
    *,
    session_id: str,
    vendor: ModelVendor,
    draft_override: Optional[str] = None,
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

    trace_dir = Path("trace", f"{session.company_name}.{vendor.value}.refine")
    trace_dir.mkdir(parents=True, exist_ok=True)
    ai_client = get_client(vendor)

    top_docs = top_docs_override or state.top_docs
    company_report = company_report_override or state.company_report or ""
    job_text = job_text_override or session.job_text
    cv_text = cv_text_override or session.cv_text
    draft_letter = draft_override or state.draft_letter or ""
    if not draft_letter:
        try:
            print(f"[PHASE] draft+refine -> {vendor.value} :: generate_letter (XLARGE)")
            draft_letter = generate_letter(cv_text, top_docs, company_report, job_text, ai_client, trace_dir)
        except Exception:
            traceback.print_exc()
            raise ValueError("Missing draft letter for refinement")

    state.company_report = company_report
    state.top_docs = top_docs

    try:
        print(f"[PHASE] refine -> {vendor.value} :: running checks (TINY)")
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

        print(f"[PHASE] refine -> {vendor.value} :: rewrite_letter (XLARGE)")
        refined = rewrite_letter(
            draft_letter,
            feedback["instruction"],
            feedback["accuracy"],
            feedback["precision"],
            feedback["company_fit"],
            feedback["user_fit"],
            feedback["human"],
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

