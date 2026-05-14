import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.responses import Response

from letter_writer_server.core.rate_limit import limiter

from letter_writer.config import get_log_level


def _env_truthy(key: str) -> bool:
    return (os.environ.get(key) or "").strip().lower() in ("1", "true", "yes")


def _configure_optional_gcp_grpc_debug_logging() -> None:
    """When LOG_GCP_DEBUG=1, raise verbosity for token refresh and Firestore gRPC (noisy)."""
    if not _env_truthy("LOG_GCP_DEBUG"):
        return
    level = logging.DEBUG
    for name in (
        "google",
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        "google.auth.transport.grpc",
        "google.api_core",
        "google.cloud.firestore",
        "grpc",
        "grpc._plugin_wrapping",
    ):
        logging.getLogger(name).setLevel(level)


# Configure root logging once so INFO logs are emitted by default.
logging.basicConfig(
    level=get_log_level(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Keep package-level loggers aligned with configured root level.
for _name in ("letter_writer", "letter_writer_server"):
    logging.getLogger(_name).setLevel(get_log_level())

_configure_optional_gcp_grpc_debug_logging()
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from starlette.middleware.sessions import SessionMiddleware as StarletteSessionMiddleware
# Use our custom session middleware instead
from letter_writer_server.core.session import SessionMiddleware
from letter_writer_server.core.config import settings

from letter_writer_server.api import admin_event_log, auth, phases, personal_data, research, documents, costs, misc, phase_feedback

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.state.limiter = limiter


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RateLimitExceeded)
    return _rate_limit_exceeded_handler(request, exc)


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-Admin-Event-Log-Key"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    cookie_name=settings.SESSION_COOKIE_NAME,
    max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
)

# Trust Proxy Headers (for HTTPS/Host behind load balancer).
# In production set TRUSTED_PROXY_HOSTS to your load balancer IP/CIDR.
# Defaults to "*" so local Docker keeps working unchanged.
_trusted_proxy_hosts = os.getenv("TRUSTED_PROXY_HOSTS", "*").split(",")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted_proxy_hosts)

# Routers
app.include_router(auth.router, prefix="/accounts/google", tags=["auth"]) # Legacy path for redirect compatibility
# Also expose under /api/auth for cleaner API
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

app.include_router(phases.router, prefix="/api/phases", tags=["phases"])
app.include_router(personal_data.router, prefix="/api", tags=["personal_data"]) # endpoints like /personal-data are defined in router
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(phase_feedback.router, prefix="/api/phase-feedback", tags=["phase_feedback"])
app.include_router(costs.router, prefix="/api/costs", tags=["costs"])
app.include_router(misc.router, prefix="/api", tags=["misc"])
app.include_router(admin_event_log.router, prefix="/api/admin/event-log", tags=["admin_event_log"])

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
