IP = "192.168.56.1"

from qdrant_client import QdrantClient

client = QdrantClient(host=IP, port=6333)

res = client.scroll(
    collection_name="my_collection",
    scroll_filter=None,
    limit=100,  # or higher
)

filenames = [point.payload.get("filename") for point in res[0] if point.payload]
print(filenames)