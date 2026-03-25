"""Structured dict types (``TypedDict``) for shapes that are stable in our own code.

**When we use TypedDict**

- Contracts we build and consume internally (RAG top docs, rerank payloads) where fields are known
  and mypy should catch typos and missing keys.

**When we stay open-ended (``dict`` / ``Dict[str, Any]``)**

- **Firestore documents** — schema evolves (new fields, nested maps); validating every read would
  be noisy; optional runtime validation can be added per feature.
- **HTTP session and agentic state blobs** — large, persisted, and iterated on; a full TypedDict
  for ``session["agentic"]`` would be a large churn; we prefer incremental typing of sub-shapes
  (e.g. ``TopDocument``) at boundaries instead.
- **Arbitrary JSON from clients** — use Pydantic models at the API layer if we need runtime checks;
  until then, handlers often use ``Dict[str, Any]`` after ``await request.json()``.

New RAG- or generation-related dicts should start here when the field set is agreed.
"""

from __future__ import annotations

from typing import Any, Dict, List, NotRequired, TypedDict


class RerankDetail(TypedDict):
    """Per-company output from LLM reranking (before merging Firestore job/letter text)."""

    score: int
    comment: str
    similarities: List[str]
    differences: List[str]


class TopDocument(TypedDict):
    """One RAG example row passed to ``generate_letter`` and returned to the UI for top docs.

    Built in ``select_top_documents`` from rerank metadata plus ``job_text`` / ``letter_text``
    from stored documents.

    ``ai_letters`` is only present when the row comes from richer stored docs (human-check /
    agentic ``human`` topic). Inner attempt objects stay ``Dict[str, Any]`` (ratings, corrections).
    """

    id: str
    company_name: str
    score: int
    similarities: List[str]
    differences: List[str]
    comment: str
    job_text: str
    letter_text: str
    ai_letters: NotRequired[List[Dict[str, Any]]]


class DocBrief(TypedDict):
    """Short bullet summary for a company (``all_briefs`` in ``select_top_documents``)."""

    similarities: List[str]
    differences: List[str]
    comment: str


class SelectTopDocumentsResult(TypedDict):
    """Return value of ``select_top_documents``."""

    top_docs: List[TopDocument]
    all_scores: dict[str, int]
    all_briefs: dict[str, DocBrief]
