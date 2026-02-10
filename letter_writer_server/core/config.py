import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Application Settings
    PROJECT_NAME: str = "Letter Writer API"
    API_V1_STR: str = "/api"
    
    # Environment
    ENVIRONMENT: str = "production"
    
    # Security
    SECRET_KEY: str = os.getenv("DJANGO_SECRET_KEY", "your-super-secret-key-change-this")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "https://localhost:8443",
        "https://localhost",
        "https://example.com"
    ]

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_SECRET", "")
    GOOGLE_REDIRECT_URI: str = "https://localhost:8443/accounts/google/login/callback/" # Default for local dev

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
        case_sensitive=True
    )

settings = Settings()
