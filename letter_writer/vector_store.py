from typing import List, Optional
import logging
import typer
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from openai import OpenAI

from .config import EMBED_MODEL

logger = logging.getLogger(__name__)


def embed(text: str, client: OpenAI) -> Vector:
    """Get embedding vector for text using OpenAI.
    
    Returns a Firestore Vector object so that find_nearest can use the field.
    Plain Python lists are stored as Firestore arrays, which the vector index ignores.
    """
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return Vector(response.data[0].embedding)


def ensure_vector_index(collection, vector_field: str = "vector", vector_size: int = 1536) -> None:
    """Ensure the Firestore vector index exists.
    
    Note: Vector indexes must be created via the Firebase Console or gcloud CLI.
    This function just verifies the index exists (by attempting a query).
    For actual index creation, use:
    gcloud firestore indexes create --collection-group=documents --query-scope=COLLECTION \
        --vector-config field-path=vector,dimension=1536,flat
    """
    # Firestore vector indexes are managed via console/CLI, not programmatically
    # This function is a placeholder to match the API
    pass


def upsert_documents(collection, doc_data_list: List[dict]) -> None:
    """Upsert documents with vectors to Firestore collection.
    
    Args:
        collection: Firestore collection reference
        doc_data_list: List of dicts, each containing document data including 'vector' field
    """
    if not doc_data_list:
        return
    
    firestore_client = getattr(collection, "_client", None)
    if firestore_client is None:
        raise RuntimeError("Collection reference does not expose a Firestore client")
    batch = firestore_client.batch()
    batch_count = 0
    max_batch_size = 500  # Firestore batch limit
    
    for doc_data in doc_data_list:
        doc_id = doc_data.get("id") or doc_data.get("document_id")
        if not doc_id:
            continue
        
        doc_ref = collection.document(doc_id)
        # Prepare document data (excluding id fields)
        data = {k: v for k, v in doc_data.items() if k not in ("id", "document_id", "_id")}
        
        batch.set(doc_ref, data, merge=True)
        batch_count += 1
        
        # Commit batch if we reach the limit
        if batch_count >= max_batch_size:
            batch.commit()
            batch = firestore_client.batch()
            batch_count = 0
    
    # Commit remaining documents
    if batch_count > 0:
        batch.commit()


def delete_documents(collection, ids: List[str]) -> None:
    """Delete documents from Firestore collection by document IDs."""
    if not ids:
        return
    
    firestore_client = getattr(collection, "_client", None)
    if firestore_client is None:
        raise RuntimeError("Collection reference does not expose a Firestore client")
    batch = firestore_client.batch()
    batch_count = 0
    max_batch_size = 500
    
    for doc_id in ids:
        doc_ref = collection.document(doc_id)
        batch.delete(doc_ref)
        batch_count += 1
        
        if batch_count >= max_batch_size:
            batch.commit()
            batch = firestore_client.batch()
            batch_count = 0
    
    if batch_count > 0:
        batch.commit()


def query_vector_similarity(
    collection,
    vector: List[float],
    limit: int = 7,
    vector_field: str = "vector",
) -> List[dict]:
    """Query Firestore for similar vectors using vector search.
    
    Args:
        collection: Firestore collection reference (CollectionReference)
        vector: Query vector (embedding)
        limit: Maximum number of results to return
        vector_field: Name of the vector field in documents
        
    Returns:
        List of documents (as dicts) with similarity scores
    """
    collection_name = getattr(collection, "id", getattr(collection, "_parent", None) and getattr(collection._parent, "id", "query"))
    logger.debug(
        "[RAG] query_vector_similarity: collection=%s, limit=%s, vector_len=%s",
        collection_name,
        limit,
        len(vector) if vector else 0,
    )
    
    # Diagnostic: check collection state
    try:
        sample = list(collection.limit(3).stream())
        logger.debug("[RAG] diagnostic: collection has docs=%s (sampled %s)", len(sample) > 0, len(sample))
        for s in sample:
            d = s.to_dict()
            has_vec = "vector" in d and d["vector"] is not None
            vec_len = len(d["vector"]) if has_vec and hasattr(d["vector"], "__len__") else "N/A"
            logger.debug(
                "[RAG] diagnostic: doc=%s, has_vector=%s, vector_len=%s, company=%s",
                s.id,
                has_vec,
                vec_len,
                d.get("company_name_original", d.get("company_name", "?")),
            )
    except Exception as diag_err:
        logger.warning("[RAG] diagnostic failed: %s", diag_err)
    
    # Firestore vector search uses find_nearest on collection
    # Note: This requires a vector index to be created first via Console or gcloud
    # Create vector query
    vector_query = collection.find_nearest(
        vector_field=vector_field,
        query_vector=Vector(vector),
        distance_measure=DistanceMeasure.COSINE,
        limit=limit,
    )
    
    # Execute the query and convert results to dicts
    results = vector_query.get()
    doc_dicts = []
    for doc in results:
        doc_dict = doc.to_dict()
        doc_dict["id"] = doc.id
        # Firestore vector search may add distance metadata
        doc_dicts.append(doc_dict)
    
    if len(doc_dicts) < limit:
        logger.warning(
            "[RAG] query_vector_similarity returned %s docs, expected up to %s",
            len(doc_dicts),
            limit,
        )
    else:
        logger.debug("[RAG] query_vector_similarity returned %s docs", len(doc_dicts))
    
    return doc_dicts


def collection_exists(collection) -> bool:
    """Check if the collection exists (has any documents)."""
    # Firestore collections exist automatically, so check if there are any documents
    try:
        first_doc = collection.limit(1).stream()
        return any(first_doc)
    except Exception:
        return False
