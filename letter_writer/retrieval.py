import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
from openai import OpenAI
import typer
from langsmith import traceable

from .clients.base import BaseClient, ModelSize

from .vector_store import embed, query_vector_similarity
from .firestore_store import get_collection
from .typed_shapes import DocBrief, RerankDetail, SelectTopDocumentsResult, TopDocument

import pandas as pd

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# Fields to strip from search results before sending to frontend
_SEARCH_RESULT_STRIP_FIELDS = {"vector", "user_id", "blocks", "ai_letters", "negative_letter_text", "notes"}


def sanitize_search_results(search_results: List[dict]) -> List[dict]:
    """Strip large/sensitive fields from Firestore document dicts for frontend display."""
    logger.debug("[RAG] sanitize_search_results: input %s docs", len(search_results))
    sanitized = []
    for doc in search_results:
        clean = {k: v for k, v in doc.items() if k not in _SEARCH_RESULT_STRIP_FIELDS}
        # Ensure we have a display-friendly company name
        if "company_name_original" in clean:
            clean["company_name"] = clean.get("company_name_original") or clean.get("company_name", "")
        # Serialize Firestore timestamps
        for ts_field in ("created_at", "updated_at"):
            if ts_field in clean and hasattr(clean[ts_field], "isoformat"):
                clean[ts_field] = clean[ts_field].isoformat()
            elif ts_field in clean and hasattr(clean[ts_field], "to_datetime"):
                clean[ts_field] = clean[ts_field].to_datetime().isoformat()
        sanitized.append(clean)
    logger.debug(
        "[RAG] sanitize_search_results: output %s docs, keys sample: %s",
        len(sanitized),
        list(sanitized[0].keys()) if sanitized else "N/A",
    )
    return sanitized

class ScoreRow(BaseModel):
    company_name: str
    comment: str
    score: int
    similarities: List[str] = Field(default_factory=list)
    differences: List[str] = Field(default_factory=list)

class ScoreTable(BaseModel):
    scores: List[ScoreRow]


def _normalize_points(points: List[str]) -> List[str]:
    """Keep up to 4 short non-empty points for UI display."""
    out: List[str] = []
    for p in points or []:
        text = str(p).strip()
        if text:
            out.append(text)
        if len(out) >= 4:
            break
    return out

def delete_documents(collection, doc_ids: List[str]):
    """Delete documents by their IDs."""
    if not doc_ids:
        return
        
    for doc_id in doc_ids:
        collection.document(doc_id).delete()

def retrieve_similar_job_offers(
    job_text: str,
    collection,
    openai_client: OpenAI,
    user_id: Optional[str] = None,
) -> List[dict]:
    """Retrieve similar job offers based on the input job text using Firestore vector search.
    
    Args:
        job_text: Job description text to search for
        collection: Firestore collection reference
        openai_client: OpenAI client for generating embeddings
        
    Returns:
        List of document dicts (Firestore returns full documents directly)
    """
    collection_name = getattr(collection, "id", "query")
    logger.debug(
        "[RAG] retrieve_similar_job_offers: job_text length=%s, collection=%s, user_scoped=%s",
        len(job_text),
        collection_name,
        bool(user_id),
    )
    vector = embed(job_text, openai_client)
    logger.debug("[RAG] embedding generated, vector length=%s", len(vector))
    # Optional per-user scope for personal document similarity.
    query_target = collection.where("user_id", "==", user_id) if user_id else collection
    # Keep retrieval pool fixed to avoid unexpected document fan-out.
    limit = 7
    results = query_vector_similarity(query_target, vector, limit=limit)
    logger.debug("[RAG] retrieve_similar_job_offers: got %s results", len(results))
    return results


@traceable(run_type="chain", name="select_top_documents")
def select_top_documents(
    search_result: List[dict],
    job_text: str,
    ai_client: BaseClient,
    trace_dir: Path,
) -> SelectTopDocumentsResult:
    """Select top documents from search results and rerank them.

    Args:
        search_result: List of document dicts from Firestore (already full documents)
        job_text: Job description text
        ai_client: AI client for reranking
        trace_dir: Directory for tracing

    Returns:
        ``{"top_docs": [...], "all_scores": {...}, "all_briefs": {...}}``
    """
    logger.debug("[RAG] select_top_documents: input %s docs", len(search_result))
    if not search_result:
        logger.debug("[RAG] select_top_documents: empty input, returning empty")
        return {"top_docs": [], "all_scores": {}, "all_briefs": {}}

    retrieved_docs: Dict[str, dict] = {}
    for doc in search_result:
        # Firestore returns full documents, use company_name_original if available, fallback to company_name
        company = doc.get("company_name_original") or doc.get("company_name")
        if company:
            # Normalize company name by stripping whitespace to match AI output
            normalized_company = company.strip()
            if normalized_company != company:
                # Log normalization if there was a mismatch
                (trace_dir / "company_name_normalization.txt").write_text(
                    f"Normalized company name: '{company}' -> '{normalized_company}'\n",
                    encoding="utf-8"
                )
            retrieved_docs[normalized_company] = doc

    logger.debug(
        "[RAG] select_top_documents: %s unique companies after dedup, sending to rerank",
        len(retrieved_docs),
    )
    reranked_docs = rerank_documents(job_text, retrieved_docs, ai_client, trace_dir)
    logger.debug("[RAG] select_top_documents: reranking returned %s scored docs", len(reranked_docs))

    # Validate that all reranked company names exist in retrieved_docs
    missing_names = [name for name in reranked_docs.keys() if name not in retrieved_docs]
    if missing_names:
        expected_names = sorted(retrieved_docs.keys())
        got_names = sorted(reranked_docs.keys())
        error_msg = (
            f"Mismatch between reranked company names and retrieved documents. "
            f"Missing from retrieved_docs: {missing_names}. "
            f"Expected company names: {expected_names}. "
            f"Got from reranking: {got_names}."
        )
        # Log detailed error to trace directory
        error_log = (
            f"PANIC: Company name mismatch in select_top_documents\n"
            f"Expected company names (from retrieved_docs): {expected_names}\n"
            f"Got from reranking (from top_docs): {got_names}\n"
            f"Missing names: {missing_names}\n"
            f"Retrieved docs count: {len(retrieved_docs)}\n"
            f"Reranked docs count: {len(reranked_docs)}\n"
        )
        (trace_dir / "error_mismatch.txt").write_text(error_log, encoding="utf-8")
        raise ValueError(error_msg)

    # top_docs: top 3 for LLM picks; all_scores: company_name -> score for display
    top3_items = list(reranked_docs.items())[:3]
    top_docs_list: List[TopDocument] = [
        {
            "id": retrieved_docs[name].get("id", ""),
            "company_name": name,
            "score": int(details["score"]),
            "similarities": list(details.get("similarities", [])),
            "differences": list(details.get("differences", [])),
            "comment": str(details.get("comment", "")),
            # Required for letter generation (generate_letter); rerank output does not include these.
            "job_text": (retrieved_docs[name].get("job_text") or ""),
            "letter_text": (retrieved_docs[name].get("letter_text") or ""),
        }
        for name, details in top3_items
    ]
    all_scores: dict[str, int] = {name: int(details["score"]) for name, details in reranked_docs.items()}
    all_briefs: dict[str, DocBrief] = {
        name: {
            "similarities": list(details.get("similarities", [])),
            "differences": list(details.get("differences", [])),
            "comment": str(details.get("comment", "")),
        }
        for name, details in reranked_docs.items()
    }
    return {
        "top_docs": top_docs_list,
        "all_scores": all_scores,
        "all_briefs": all_briefs,
    }

@traceable(run_type="chain", name="rerank_documents")
def rerank_documents(
    job_text: str, docs: dict, ai_client: BaseClient, trace_dir: Path
) -> Dict[str, RerankDetail]:
    """Ask the model to score docs and return company_name -> detail dict."""
    
    # Prepare mapping of doc id -> company_name for scoring
    mapping = {i: {"company_name": name, "job_text": data["job_text"]} for i, (name, data) in enumerate(docs.items())}
    mapping_json = json.dumps(mapping, indent=2)

    system = (
        "You are an expert in scoring the similarity of job descriptions to a target job description. \n\n"
        "Given the original job description and a set of other job descriptions with their company names, "
        "score each on how similar it is to the original on a scale of 1-10. \n"
        "Reference: \n"
        "- 10 = Nearly identical in both focus and tasks\n"
        "- 8 = Shares most key tasks, but differs on one major aspect\n"
        "- 6 = Partial overlap (e.g. Python and C++ vs Python and React)\n"
        "- 4 = Some overlap, but signiticantly different jobs (Example: Frontend vs Backend programmer)\n"
        "- 2 = Only the most basic tools and duties are shared (Example: Programmer vs Data Scientist) \n\n"
        "If the job description is not similar to the original, score it 1. \n\n"
        "For each job, include:\n"
        "- similarities: 1 to 4 short bullet-like points\n"
        "- differences: 1 to 4 short bullet-like points\n"
        "Keep points concise and specific.\n\n"
        f"Return a JSON object matching the schema: {ScoreTable.model_json_schema()}. "
        "Return ONLY the JSON object, no wrappers.\n\n"
    )
    prompt = "Original Job Description:\n" + job_text + "\n\nOther Descriptions (JSON):\n" + mapping_json
    scores_json = ai_client.call(ModelSize.LARGE, system, [prompt])

    # remove wrapping '''json if present
    if scores_json.startswith("```json"):
        scores_json = scores_json[len("```json"):]
    if scores_json.endswith("```"):
        scores_json = scores_json[:-len("```")]
    
    try:
        scores = ScoreTable.model_validate_json(scores_json)
    except ValidationError as e:
        typer.echo(f"[ERROR] Failed to parse scores with error {e}. The scores are: {scores_json}")
        raise e
    
    score_table = pd.DataFrame([s.model_dump() for s in scores.scores])
    score_table.sort_values(by="score", ascending=False, inplace=True)
    score_table.to_json(trace_dir / "retrieved_docs.json", orient="records", indent=2)

    # return all scored docs as dict company_name -> details (top 3 used for picks, all for display)
    out: Dict[str, RerankDetail] = {}
    for _, row in score_table.iterrows():
        out[str(row["company_name"])] = {
            "score": int(row["score"]),
            "comment": str(row.get("comment", "")),
            "similarities": _normalize_points(row.get("similarities", [])),
            "differences": _normalize_points(row.get("differences", [])),
        }
    return out
