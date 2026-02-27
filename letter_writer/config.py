import os
import logging
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


def get_extraction_model() -> str:
    """Return extraction model name from env, with a safe default."""
    return env_default("EXTRACTION_MODEL", "gpt-5-nano") or "gpt-5-nano"


def get_log_level() -> int:
    """Return logging level from env, defaulting to INFO."""
    level_name = (env_default("LOG_LEVEL", "INFO") or "INFO").strip().upper()
    return getattr(logging, level_name, logging.INFO)

# Load environment variables when module is imported
load_env() 