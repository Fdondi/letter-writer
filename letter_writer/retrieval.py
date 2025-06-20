import json
from typing import List
from pathlib import Path
from qdrant_client import QdrantClient
from openai import OpenAI

from .config import COLLECTION_NAME
from .vector_store import embed

def retrieve_similar_job_offers(job_text: str, openai_client: OpenAI, qdrant_client: QdrantClient, trace_dir: Path) -> List[dict]:
    """Retrieve and rerank similar job offers based on the input job text."""
    vector = embed(job_text, openai_client)
    search_result = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=7,
    )

    retrieved_docs = [r.payload for r in search_result]
    retrieved_docs_names = '\n'.join([r.payload["company_name"] for r in search_result])
    top_docs = rerank_documents(job_text, retrieved_docs, openai_client)
    top_docs_names = '\n'.join([d["company_name"] for d in top_docs])
    debug_str = f"Initially retrieved:\n{retrieved_docs_names}\n\nThen selected:\n{top_docs_names}\n\n"
    print(debug_str)
    (trace_dir / "retrieved_docs.txt").write_text(debug_str, encoding="utf-8")
    return top_docs

def rerank_documents(job_text: str, docs: List[dict], client: OpenAI) -> List[dict]:
    """Ask the model to score docs and return top 3."""
    from .generation import chat  # Import here to avoid circular imports
    
    # Prepare mapping of doc id -> company_name for scoring
    mapping = {i: {"company_name": d["company_name"], "job_text": d["job_text"]} for i, d in enumerate(docs)}
    mapping_json = json.dumps(mapping, indent=2)

    system = (
        "You are an expert in scoring the similarity of job descriptions to a target job description. \n\n"
        "Given the original job description and a set of other job descriptions with their company names, "
        "score each on how similar it is to the original on a scale of 1-10. \n\n"
        "Return a JSON map of letter_company_name -> score out of 10. Keep output strictly JSON.\n\n"
    )
    prompt = "Original Job Description:\n" + job_text + "\n\nOther Descriptions (JSON):\n" + mapping_json

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    raw_scores = chat(messages, client, model="o4-mini")

    try:
        scores = json.loads(raw_scores)
        # Convert company_name scores back to indices
        index_scores = {}
        for i, doc in enumerate(docs):
            company_name = doc["company_name"]
            index_scores[str(i)] = scores.get(company_name, 5)
    except json.JSONDecodeError:
        # Fallback: naive equal scoring
        index_scores = {str(i): 5 for i in range(len(docs))}

    # Sort by score desc, pick top 3
    ranked_indices = sorted(range(len(docs)), key=lambda i: float(index_scores.get(str(i), 0)), reverse=True)[:3]
    return [docs[i] for i in ranked_indices] 