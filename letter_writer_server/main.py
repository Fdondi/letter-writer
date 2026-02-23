import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure agentic and API logs are visible (e.g. when running: podman logs letter-writer-backend)
for _name in ("letter_writer", "letter_writer_server"):
    logging.getLogger(_name).setLevel(logging.INFO)
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from starlette.middleware.sessions import SessionMiddleware as StarletteSessionMiddleware
# Use our custom session middleware instead
from letter_writer_server.core.session import SessionMiddleware
from letter_writer_server.core.config import settings

from letter_writer_server.api import auth, phases, personal_data, research, documents, costs, misc

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    cookie_name=settings.SESSION_COOKIE_NAME,
    max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
)

# Trust Proxy Headers (for HTTPS/Host behind Nginx)
# Added last to be executed first
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Routers
app.include_router(auth.router, prefix="/accounts/google", tags=["auth"]) # Legacy path for redirect compatibility
# Also expose under /api/auth for cleaner API
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

app.include_router(phases.router, prefix="/api/phases", tags=["phases"])
app.include_router(personal_data.router, prefix="/api", tags=["personal_data"]) # endpoints like /personal-data are defined in router
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(costs.router, prefix="/api/costs", tags=["costs"])
app.include_router(misc.router, prefix="/api", tags=["misc"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.on_event("startup")
def _log_langsmith_status():
    tracing = (os.environ.get("LANGSMITH_TRACING") or "").strip().lower() == "true"
    project = os.environ.get("LANGSMITH_PROJECT", "")
    endpoint = os.environ.get("LANGSMITH_ENDPOINT", "")
    key_set = bool(os.environ.get("LANGSMITH_API_KEY"))
    log = logging.getLogger("letter_writer_server.main")
    if tracing and key_set:
        log.info(
            "LangSmith tracing enabled | project=%s | endpoint=%s",
            project or "(default)",
            endpoint or "(default)",
        )
    else:
        log.info(
            "LangSmith tracing disabled (LANGSMITH_TRACING=%s, API key set=%s)",
            os.environ.get("LANGSMITH_TRACING", ""),
            key_set,
        )
