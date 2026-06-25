from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.availability import router as availability_router
from backend.api.profile import router as profile_router
from backend.api.budget import router as budget_router
from backend.api.contracts import router as contracts_router
from backend.api.enrichment import router as enrichment_router
from backend.api.finalists import router as finalists_router
from backend.api.history import router as history_router
from backend.api.jobs import router as jobs_router
from backend.api.preferences import router as preferences_router
from backend.api.proposals import router as proposals_router
from backend.api.scanner import router as scanner_router
from backend.config import settings
from backend.db.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup / shutdown logic for the application."""
    await create_tables()
    yield


app = FastAPI(
    title="Contract Finder API",
    description="AI-powered contract discovery and proposal generation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routers ────────────────────────────────────────────────────
app.include_router(contracts_router)
app.include_router(scanner_router)
app.include_router(proposals_router)
app.include_router(availability_router)
app.include_router(budget_router)
app.include_router(history_router)
app.include_router(jobs_router)
app.include_router(preferences_router)
app.include_router(enrichment_router)
app.include_router(finalists_router)
app.include_router(profile_router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "contract-finder-api"}
