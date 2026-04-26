"""
API Request/Response Schemas — Pydantic models for the FastAPI boundary.

These are separate from the internal domain schemas (schemas.py, ingestion/contracts.py)
to enforce a clean API contract that can evolve independently of internal models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# AGENTS & VALIDATION (Sprint 4)
# ──────────────────────────────────────────────────────────────────────────────

class ValidationTrace(BaseModel):
    """
    Cryptographic proof of validation for LLM-generated citations.
    Ensures that every reference cited by the AI exists and is unaltered.
    """
    is_valid: bool = Field(..., description="True if all claimed references are verified in the graph")
    verified_nodes: List[str] = Field(default_factory=list, description="List of node IDs successfully found")
    missing_nodes: List[str] = Field(default_factory=list, description="List of IDs hallucinated by the LLM")
    cryptographic_hashes: Dict[str, str] = Field(default_factory=dict, description="Mapping of node ID to its SHA-256 hash")
    error_message: Optional[str] = Field(None, description="Detailed reason for validation failure")
    cypher_query_executed: Optional[str] = Field(None, description="The deterministic Cypher query used for verification")


# ──────────────────────────────────────────────────────────────────────────────
# Health & Metadata
# ──────────────────────────────────────────────────────────────────────────────

class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class HealthResponse(BaseModel):
    status: HealthStatus = Field(..., description="Service health status")
    version: str = Field(..., description="API version")
    engine_ready: bool = Field(False, description="Whether the compliance engine is initialized")
    graph_ready: bool = Field(False, description="Whether the knowledge graph is loaded")
    rules_indexed: int = Field(0, description="Number of EASA rules indexed")
    manual_chunks_loaded: int = Field(0, description="Number of manual chunks loaded")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TraceabilityLog(BaseModel):
    """
    Standardized explicability log (XAI) for regulatory audits.
    Provides proof of data origin and integrity.
    """
    cypher_query_executed: str = Field(..., description="The deterministic Cypher query used for verification")
    node_hashes: Dict[str, str] = Field(..., description="Proof of integrity for all cited nodes")
    validation_status: bool = Field(..., description="Absolute boolean validation status")
    anonymized: bool = Field(True, description="Whether the input was sanitized via Presidio")
    execution_time_ms: float = Field(0.0, description="Processing time for the validation layer")


class ComplianceResponse(BaseModel):
    """
    Final output for the ReguMap-AI Human-in-the-loop dashboard.
    Combines probabilistic reasoning (AI) with deterministic proof (Traceability).
    """
    answer: str = Field(..., description="The certifiable compliance analysis")
    cited_references: List[str] = Field(default_factory=list)
    traceability_log: TraceabilityLog
    is_valid: bool = True
    iterations: int = 1


# ──────────────────────────────────────────────────────────────────────────────
# Compliance Audit
# ──────────────────────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    """Request body for POST /api/v1/audit/compliance."""
    requirement_id: str = Field(
        ..., description="EASA rule ID to audit (e.g., 'ADR.OR.B.005')"
    )
    refined_question: str = Field(
        "Standard Compliance Check",
        description="Optional refined query for hybrid search context",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "requirement_id": "ADR.OR.B.005",
                "refined_question": "Does the OM-A document the aerodrome management system?",
            }]
        }
    }


class AuditStatusResponse(str, Enum):
    COMPLIANT = "Compliant"
    PARTIAL = "Partial"
    GAP = "Gap"
    REQUIRES_HUMAN_REVIEW = "Requires Human Review"
    INFORMATIONAL = "Informational"


class AuditResultResponse(BaseModel):
    """Response body for a single compliance audit result."""
    requirement_id: str
    status: AuditStatusResponse
    evidence_quote: str
    source_reference: str
    confidence_score: float
    suggested_fix: Optional[str] = None
    cross_refs_used: List[str] = Field(default_factory=list)
    validation_score: Optional[float] = None
    evidence_crop_path: Optional[str] = None
    agent_trace: Optional[str] = None


class BatchAuditRequest(BaseModel):
    """Request body for POST /api/v1/audit/batch."""
    requirement_ids: List[str] = Field(
        ..., description="List of EASA rule IDs to audit",
        min_length=1,
        max_length=50,
    )
    refined_question: str = Field("Standard Compliance Check")


class BatchAuditResponse(BaseModel):
    """Response body for batch compliance audit."""
    results: List[AuditResultResponse]
    total: int
    compliant: int
    partial: int
    gaps: int
    requires_review: int
    duration_seconds: float


# ──────────────────────────────────────────────────────────────────────────────
# Search & Q&A
# ──────────────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    """Request body for POST /api/v1/search."""
    query: str = Field(..., description="Search query (rule ID or natural language)")
    domain_filter: Optional[str] = Field(None, description="Domain filter (e.g., 'air-ops')")
    k: int = Field(5, description="Number of results", ge=1, le=50)


class SearchResultItem(BaseModel):
    rule_id: str
    text: str
    source_title: Optional[str] = None
    domain: Optional[str] = None
    score: float


class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    total: int
    query: str


class QARequest(BaseModel):
    """Request body for POST /api/v1/qa."""
    question: str = Field(..., description="Regulatory question in natural language")
    domain_filter: Optional[str] = Field(None)


class QAResponse(BaseModel):
    answer: str
    sources: List[SearchResultItem] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Knowledge Graph
# ──────────────────────────────────────────────────────────────────────────────

class GraphStatsResponse(BaseModel):
    """Response for GET /api/v1/graph/stats."""
    total_nodes: int
    total_edges: int
    node_types: Dict[str, int] = Field(default_factory=dict)
    edge_types: Dict[str, int] = Field(default_factory=dict)
    density: float = 0.0


class GraphTraverseRequest(BaseModel):
    """Request for POST /api/v1/graph/traverse."""
    node_id: str = Field(..., description="Starting node ID for traversal")
    depth: int = Field(2, description="BFS depth", ge=0, le=5)


class GraphNodeResponse(BaseModel):
    id: str
    node_type: Optional[str] = None
    label: Optional[str] = None
    hop: int = 0
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphTraverseResponse(BaseModel):
    root: str
    depth: int
    nodes: List[GraphNodeResponse]
    total: int


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion
# ──────────────────────────────────────────────────────────────────────────────

class IngestionStatusResponse(BaseModel):
    """Response for GET /api/v1/ingest/status."""
    easa_rules_count: int = 0
    manual_chunks_count: int = 0
    s1000d_modules_count: int = 0
    pre_filtered: bool = False
    graph_built: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Error
# ──────────────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    error_type: Optional[str] = None
    trace: Optional[str] = None
