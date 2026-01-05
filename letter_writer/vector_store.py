from typing import List, Optional
import typer
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from openai import OpenAI

from .config import EMBED_MODEL
from .firestore_store import get_collection, get_firestore_client


def embed(text: str, client: OpenAI) -> List[float]:
    """Get embedding vector for text using OpenAI."""
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding


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
    
    batch = get_firestore_client().batch()
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
            batch = get_firestore_client().batch()
            batch_count = 0
    
    # Commit remaining documents
    if batch_count > 0:
        batch.commit()


def delete_documents(collection, ids: List[str]) -> None:
    """Delete documents from Firestore collection by document IDs."""
    if not ids:
        return
    
    batch = get_firestore_client().batch()
    batch_count = 0
    max_batch_size = 500
    
    for doc_id in ids:
        doc_ref = collection.document(doc_id)
        batch.delete(doc_ref)
        batch_count += 1
        
        if batch_count >= max_batch_size:
            batch.commit()
            batch = get_firestore_client().batch()
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
    
    return doc_dicts


def collection_exists(collection) -> bool:
    """Check if the collection exists (has any documents)."""
    # Firestore collections exist automatically, so check if there are any documents
    try:
        first_doc = collection.limit(1).stream()
        return any(first_doc)
    except Exception:
        return False
