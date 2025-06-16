from typing import List, Optional
import typer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from openai import OpenAI

from .config import COLLECTION_NAME, EMBED_MODEL

def get_openai_client(api_key: Optional[str] = None) -> OpenAI:
    """Get OpenAI client with API key validation."""
    if not api_key:
        typer.echo("[ERROR] OpenAI API key not provided. Use --openai_key or set OPENAI_API_KEY env variable.")
        raise typer.Exit(code=1)
    return OpenAI(api_key=api_key)

def embed(text: str, client: OpenAI) -> List[float]:
    """Get embedding vector for text using OpenAI."""
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding

def get_qdrant_client(host: str, port: int) -> QdrantClient:
    """Get Qdrant client instance."""
    return QdrantClient(host=host, port=port)

def ensure_collection(client: QdrantClient, vector_size: int = 1536) -> None:
    """Ensure the Qdrant collection exists, create if not."""
    if COLLECTION_NAME in [c.name for c in client.get_collections().collections]:
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qdrant_models.VectorParams(size=vector_size, distance=qdrant_models.Distance.COSINE),
    )

def upsert_documents(client: QdrantClient, points: List[qdrant_models.PointStruct]) -> None:
    """Upsert documents to Qdrant collection."""
    if points:
        client.upsert(collection_name=COLLECTION_NAME, points=points)
    
def collection_exists(client: QdrantClient) -> bool:
    """Check if the collection exists."""
    return COLLECTION_NAME in [c.name for c in client.get_collections().collections] 