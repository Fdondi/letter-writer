import os
import sys
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

def _require_secret_key() -> str:
    key = os.getenv("APP_SECRET_KEY") or os.getenv("DJANGO_SECRET_KEY")
    if not key:
        print(
            "FATAL: APP_SECRET_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"",
            file=sys.stderr,
        )
        sys.exit(1)
    return key

class Settings(BaseSettings):
    # Application Settings
    PROJECT_NAME: str = "Letter Writer API"
    API_V1_STR: str = "/api"

    # Environment
    ENVIRONMENT: str = "production"

    # Security
    SECRET_KEY: str = _require_secret_key()
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS — space/comma-separated list of allowed origins via env var.
    # Localhost origins are kept for local Docker dev; add your production
    # domain via BACKEND_CORS_EXTRA_ORIGINS="https://myapp.run.app".
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "https://localhost:8443",
        "https://localhost",
    ]

    @property
    def cors_origins(self) -> List[str]:
        extra = os.getenv("BACKEND_CORS_EXTRA_ORIGINS", "")
        extra_list = [o.strip() for o in extra.replace(",", " ").split() if o.strip()]
        return self.BACKEND_CORS_ORIGINS + extra_list

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "https://localhost:8443/accounts/google/login/callback/",
    )

    # Firestore
    GOOGLE_CLOUD_PROJECT: Optional[str] = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("FIRESTORE_PROJECT_ID")
    FIRESTORE_DATABASE: Optional[str] = os.getenv("FIRESTORE_DATABASE")

    # Redis (for Cost Tracking)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # BigQuery (for Cost Analytics)
    BIGQUERY_DATASET: str = os.getenv("BIGQUERY_DATASET", "letter_writer_costs")

    # Session
    SESSION_SECRET_KEY: str = SECRET_KEY  # Reuse secret key for session signing
    SESSION_COOKIE_NAME: str = "letter_writer_session"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

settings = Settings()
