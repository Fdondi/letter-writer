import json
from typing import List, Dict
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import ScoredPoint
from openai import OpenAI
import typer

from .clients.base import BaseClient, ModelSize

from .config import COLLECTION_NAME
from .vector_store import embed

import pandas as pd

from pydantic import BaseModel, ValidationError

from .mongo_store import documents_by_ids, get_db

class ScoreRow(BaseModel):
    company_name: str
    comment: str
    score: int

class ScoreTable(BaseModel):
    scores: List[ScoreRow]

def retrieve_similar_job_offers(job_text: str, qdrant_client: QdrantClient, openai_client: OpenAI) -> List[ScoredPoint]:
    """Retrieve and rerank similar job offers based on the input job text."""
    vector = embed(job_text, openai_client)
    # qdrant-client 1.16 uses query_points (search/search_points are not available here)
    response = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=7,
        with_payload=True,
    )
    return list(response.points or [])

def _hydrate_documents(search_result: List[ScoredPoint]) -> List[dict]:
    """Fetch documents from Mongo if payload only contains ids. Fallback to legacy payloads."""
    mongo_docs: List[dict] = []
    legacy_docs: List[dict] = []

    doc_ids = []
    for point in search_result:
        payload = point.payload or {}
        if payload.get("document_id"):
            doc_ids.append(str(payload["document_id"]))
        elif payload.get("company_name") and payload.get("letter_text"):
            # Legacy payload already contains needed fields
            legacy_docs.append(payload)

    if doc_ids:
        db = get_db()
        mongo_docs = documents_by_ids(db, doc_ids)

    return legacy_docs + mongo_docs


def select_top_documents(
    search_result: List[ScoredPoint],
    job_text: str,
    ai_client: BaseClient,
    trace_dir: Path,
) -> List[dict]:
    documents = _hydrate_documents(search_result)
    if not documents:
        return []

    retrieved_docs: Dict[str, dict] = {}
    for doc in documents:
        company = doc.get("company_name")
        if company:
            retrieved_docs[company] = doc

    top_docs = rerank_documents(job_text, retrieved_docs, ai_client, trace_dir)

    return [
        {
            "score": score,
            **retrieved_docs[name],
        }
        for name, score in top_docs.items()
    ]

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

    # return top 3 documents as dicts with company_name and score
    top3 = score_table.head(3)
    return {row["company_name"]: row["score"] for _, row in top3.iterrows()}