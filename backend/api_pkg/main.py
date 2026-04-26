"""
ReguMap-AI — FastAPI Application Entry Point.

This is the decoupled AI engine, callable via HTTP instead of being
locked inside Streamlit. The entire 4-agent compliance pipeline,
hybrid search, knowledge graph, and ingestion are exposed as REST endpoints.

Run:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Production (Cloud Run / GCP):
    uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 1
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_pkg.dependencies import initialize_engine, is_engine_ready, shutdown_engine
from api_pkg.routes import compliance, graph, ingestion, search
from api_pkg.schemas import HealthResponse, HealthStatus
from security.vault import verify_session_token
from fastapi import Security, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("regumap-ai")

# ──────────────────────────────────────────────────────────────────────────────
# API Metadata
# ──────────────────────────────────────────────────────────────────────────────

API_VERSION = "1.0.0"
API_TITLE = "ReguMap-AI Engine"
API_DESCRIPTION = """
**ReguMap-AI** — Aeronautical Regulatory Compliance Engine.

Decoupled AI engine for EASA/FAA compliance auditing. Exposes the
4-agent pipeline (Researcher → Conflict Detector → Auditor → Critic),
hybrid search (FAISS + BM25 + Graph), and S1000D ingestion via REST API.
Built on the **'Certifiable Robustness'** framework (Symbolic Validation) for EASA/FAA compliance.

### Architecture
- **Backend**: FastAPI + Python (AI Engine)
- **Search**: FAISS (vector) + BM25 (keyword) + NetworkX/Neo4j (graph)
- **LLM**: Google Gemini 1.5 Pro (via LangChain)
- **Security**: Fernet encryption, PII redaction, RBAC

### Endpoints
- `/api/v1/audit/` — Compliance audit (single + batch)
- `/api/v1/search` — Hybrid regulatory search
- `/api/v1/qa` — Regulatory Q&A
- `/api/v1/graph/` — Knowledge graph traversal
- `/api/v1/ingest/` — Document ingestion (EASA XML, PDF, S1000D)
"""


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan (startup/shutdown)
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages engine lifecycle: init on startup, cleanup on shutdown."""
    logger.info("=" * 60)
    logger.info("ReguMap-AI Engine starting...")
    logger.info("=" * 60)

    try:
        initialize_engine()
        logger.info("Engine initialized. Ready to accept requests.")
    except EnvironmentError as e:
        logger.warning(f"Engine init deferred: {e}")
        logger.warning("Server starting without engine. Set GEMINI_API_KEY to enable.")

    yield  # Application runs here

    logger.info("Shutting down ReguMap-AI Engine...")
    shutdown_engine()
    logger.info("Shutdown complete.")


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={"persistAuthorization": True},
)

# ── Security Schemes (OAS 3.1) ────────────────────────────────────────────────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter JWT token from ReguMap-AI Gateway"
        }
    }
    # Apply security globally for Swagger UI visibility
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

from fastapi.openapi.utils import get_openapi
app.openapi = custom_openapi

# CORS — allow the React PWA frontend (and dev servers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # React dev server
        "http://localhost:5173",      # Vite dev server
        "http://localhost:8081",      # Local manual test frontend
        "https://*.run.app",          # Cloud Run
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# Security Dependency (Zero-Trust)
# ──────────────────────────────────────────────────────────────────────────────

auth_scheme = HTTPBearer()

def validate_user(token: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    MOCK VALIDATION for Local Manual Test (Bypassing Gateway).
    """
    return {"user_id": "QA-Tester", "role": "ADMIN"}

# ──────────────────────────────────────────────────────────────────────────────
# Route Registration
# ──────────────────────────────────────────────────────────────────────────────

API_PREFIX = "/api/v1"

# Apply Zero-Trust validation to all functional routers (DISABLED FOR MANUAL TEST)
app.include_router(compliance.router, prefix=API_PREFIX)
app.include_router(search.router, prefix=API_PREFIX)
app.include_router(graph.router, prefix=API_PREFIX)
app.include_router(ingestion.router, prefix=API_PREFIX)


# ──────────────────────────────────────────────────────────────────────────────
# Health Check (no prefix — root level)
# ──────────────────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
)
async def health_check():
    """Returns service health, engine readiness, and loaded data counts."""
    from api_pkg.dependencies import _engine_instance

    engine = _engine_instance
    if engine is None:
        return HealthResponse(
            status=HealthStatus.DEGRADED,
            version=API_VERSION,
            engine_ready=False,
        )

    return HealthResponse(
        status=HealthStatus.OK,
        version=API_VERSION,
        engine_ready=True,
        graph_ready=engine.knowledge_graph.is_built(),
        rules_indexed=len(engine._all_rules),
        manual_chunks_loaded=len(engine.manual_chunks),
    )


@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    """Root redirect to API docs."""
    return {
        "service": "ReguMap-AI Engine",
        "version": API_VERSION,
        "docs": "/docs",
        "health": "/health",
    }
