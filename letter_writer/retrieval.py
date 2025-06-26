import json
from typing import List
from pathlib import Path
from qdrant_client import QdrantClient
from openai import OpenAI

from .config import COLLECTION_NAME
from .vector_store import embed

import pandas as pd

from pydantic import BaseModel, ValidationError
from typing import List

class ScoreRow(BaseModel):
    company_name: str
    comment: str
    score: int

class ScoreTable(BaseModel):
    scores: List[ScoreRow]

def retrieve_similar_job_offers(job_text: str, openai_client: OpenAI, qdrant_client: QdrantClient, trace_dir: Path) -> List[dict]:
    """Retrieve and rerank similar job offers based on the input job text."""
    vector = embed(job_text, openai_client)
    search_result = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=7,
    )

    retrieved_docs = {r.payload["company_name"]: r.payload for r in search_result}
    top_docs = rerank_documents(job_text, retrieved_docs, openai_client, trace_dir)
    
    return [{
        "score": score,
        **retrieved_docs[name],
    } for name, score in top_docs.items()]

def rerank_documents(job_text: str, docs: dict, client: OpenAI, trace_dir: Path) -> dict:
    """Ask the model to score docs and return top 3 as dicts with company_name and score."""
    from .generation import chat  # Import here to avoid circular imports
    
    # Prepare mapping of doc id -> company_name for scoring
    mapping = {i: {"company_name": name, "job_text": data["job_text"]} for i, (name, data) in enumerate(docs.items())}
    mapping_json = json.dumps(mapping, indent=2)

    system = (
        "You are an expert in scoring the similarity of job descriptions to a target job description. \n\n"
        "Given the original job description and a set of other job descriptions with their company names, "
        "score each on how similar it is to the original on a scale of 1-10. \n\n"
        f"Return an object matching the schema: {ScoreTable.model_json_schema()}.\n\n"
    )
    prompt = "Original Job Description:\n" + job_text + "\n\nOther Descriptions (JSON):\n" + mapping_json
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    scores_json = chat(messages, client, model="o4-mini")

    scores = ScoreTable.model_validate_json(scores_json)

    score_table = pd.DataFrame([s.model_dump() for s in scores.scores])
    score_table.sort_values(by="score", ascending=False, inplace=True)
    score_table.to_json(trace_dir / "retrieved_docs.json", orient="records", indent=2)

    # return top 3 documents as dicts with company_name and score
    top3 = score_table.head(3)
    return {row["company_name"]: row["score"] for _, row in top3.iterrows()}