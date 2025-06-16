import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Constants
COLLECTION_NAME = "job_offers"
EMBED_MODEL = "text-embedding-3-small"
TRACE_DIR = Path("trace")

def load_env() -> None:
    """Load environment variables from a .env file if present."""
    load_dotenv()

def env_default(key: str, default: Optional[str] = None) -> Optional[str]:
    """Return value from env or default."""
    return os.getenv(key, default)

# Load environment variables when module is imported
load_env() 