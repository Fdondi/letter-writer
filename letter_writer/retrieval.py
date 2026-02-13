import json
from typing import List, Dict
from pathlib import Path
from openai import OpenAI
import typer
from langsmith import traceable

from .clients.base import BaseClient, ModelSize

from .vector_store import embed, query_vector_similarity
from .firestore_store import get_collection

import pandas as pd

from pydantic import BaseModel, ValidationError

# Fields to strip from search results before sending to frontend
_SEARCH_RESULT_STRIP_FIELDS = {"vector", "user_id", "blocks", "ai_letters", "negative_letter_text", "notes"}


def sanitize_search_results(search_results: List[dict]) -> List[dict]:
    """Strip large/sensitive fields from Firestore document dicts for frontend display."""
    print(f"[RAG] sanitize_search_results: input {len(search_results)} docs")
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
    print(f"[RAG] sanitize_search_results: output {len(sanitized)} docs, keys sample: {list(sanitized[0].keys()) if sanitized else 'N/A'}")
    return sanitized

class ScoreRow(BaseModel):
    company_name: str
    comment: str
    score: int

class ScoreTable(BaseModel):
    scores: List[ScoreRow]

def delete_documents(collection, doc_ids: List[str]):
    """Delete documents by their IDs."""
    if not doc_ids:
        return
        
    for doc_id in doc_ids:
        collection.document(doc_id).delete()

def retrieve_similar_job_offers(job_text: str, collection, openai_client: OpenAI) -> List[dict]:
    """Retrieve similar job offers based on the input job text using Firestore vector search.
    
    Args:
        job_text: Job description text to search for
        collection: Firestore collection reference
        openai_client: OpenAI client for generating embeddings
        
    Returns:
        List of document dicts (Firestore returns full documents directly)
    """
    print(f"[RAG] retrieve_similar_job_offers: job_text length={len(job_text)}, collection={collection.id}")
    vector = embed(job_text, openai_client)
    print(f"[RAG] embedding generated, vector length={len(vector)}")
    # Firestore vector search returns full documents directly
    results = query_vector_similarity(collection, vector, limit=7)
    print(f"[RAG] retrieve_similar_job_offers: got {len(results)} results")
    return results


@traceable(run_type="chain", name="select_top_documents")
def select_top_documents(
    search_result: List[dict],
    job_text: str,
    ai_client: BaseClient,
    trace_dir: Path,
) -> List[dict]:
    """Select top documents from search results and rerank them.
    
    Args:
        search_result: List of document dicts from Firestore (already full documents)
        job_text: Job description text
        ai_client: AI client for reranking
        trace_dir: Directory for tracing
        
    Returns:
        List of top documents with scores
    """
    print(f"[RAG] select_top_documents: input {len(search_result)} docs")
    if not search_result:
        print(f"[RAG] select_top_documents: empty input, returning empty")
        return {"top_docs": [], "all_scores": {}}

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

    print(f"[RAG] select_top_documents: {len(retrieved_docs)} unique companies after dedup, sending to rerank")
    top_docs = rerank_documents(job_text, retrieved_docs, ai_client, trace_dir)
    print(f"[RAG] select_top_documents: reranking returned {len(top_docs)} scored docs")

    # Validate that all reranked company names exist in retrieved_docs
    missing_names = [name for name in top_docs.keys() if name not in retrieved_docs]
    if missing_names:
        expected_names = sorted(retrieved_docs.keys())
        got_names = sorted(top_docs.keys())
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
            f"Reranked docs count: {len(top_docs)}\n"
        )
        (trace_dir / "error_mismatch.txt").write_text(error_log, encoding="utf-8")
        raise ValueError(error_msg)

    # top_docs: top 3 for LLM picks; all_scores: company_name -> score for display
    top3_items = list(top_docs.items())[:3]
    top_docs_list = [
        {
            "id": retrieved_docs[name].get("id", ""),
            "company_name": name,
            "score": score,
        }
        for name, score in top3_items
    ]
    return {"top_docs": top_docs_list, "all_scores": dict(top_docs)}

@traceable(run_type="chain", name="rerank_documents")
def rerank_documents(job_text: str, docs: dict, ai_client: BaseClient, trace_dir: Path) -> dict:
    """Ask the model to score docs and return top 3 as dicts with company_name and score."""
    
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
        f"Return a JSON object matching the schema: {ScoreTable.model_json_schema()}. "
        "Return ONLY the JSON object, no wrappers.\n\n"
    )
    prompt = "Original Job Description:\n" + job_text + "\n\nOther Descriptions (JSON):\n" + mapping_json
    scores_json = ai_client.call(ModelSize.LARGE, system=system, user_messages=[prompt])

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

    # return all scored docs as dict company_name -> score (top 3 used for picks, all for display)
    return {row["company_name"]: row["score"] for _, row in score_table.iterrows()}
