from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

# Session
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    cookie_name=settings.SESSION_COOKIE_NAME,
    max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
)

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
