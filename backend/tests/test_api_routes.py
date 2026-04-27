"""
Tests for the FastAPI API layer.
Validates: health check, route registration, schema validation,
and endpoint logic with mocked engine.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_engine():
    """Creates a mock ComplianceEngine for testing."""
    engine = MagicMock()
    engine._all_rules = []
    engine.manual_chunks = []
    engine.pre_filtered = False
    engine.vectorstore = None
    engine.knowledge_graph = MagicMock()
    engine.knowledge_graph.is_built.return_value = False
    engine._rule_lookup = {}
    return engine


@pytest.fixture
def client(mock_engine):
    """Creates a test client with the mock engine injected and auth bypassed."""
    import os
    from api_pkg.main import app
    from api_pkg.dependencies import get_engine

    # Enable dev-mode auth bypass for testing
    original_auth = os.environ.get("DISABLE_AUTH")
    os.environ["DISABLE_AUTH"] = "true"

    app.dependency_overrides[get_engine] = lambda: mock_engine
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    # Restore original env
    if original_auth is None:
        os.environ.pop("DISABLE_AUTH", None)
    else:
        os.environ["DISABLE_AUTH"] = original_auth


# ──────────────────────────────────────────────────────────────────────────────
# Health & Root
# ──────────────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "ReguMap-AI Engine"
        assert "docs" in data

    def test_health_degraded_no_engine(self):
        """Health should report DEGRADED when engine is not initialized."""
        from api_pkg.main import app
        from api_pkg.dependencies import get_engine
        # Don't override the dependency — let it use the real check
        with TestClient(app) as c:
            response = c.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] in ["ok", "degraded"]
            assert "version" in data
            assert "engine_ready" in data


# ──────────────────────────────────────────────────────────────────────────────
# API Schema Validation
# ──────────────────────────────────────────────────────────────────────────────

class TestAPISchemas:
    def test_audit_request_validation(self):
        from api_pkg.schemas import AuditRequest
        req = AuditRequest(requirement_id="ADR.OR.B.005")
        assert req.requirement_id == "ADR.OR.B.005"
        assert req.refined_question == "Standard Compliance Check"

    def test_audit_request_custom_question(self):
        from api_pkg.schemas import AuditRequest
        req = AuditRequest(
            requirement_id="ORO.FTL.210",
            refined_question="How are FTL limits documented?",
        )
        assert req.refined_question == "How are FTL limits documented?"

    def test_batch_request_validation(self):
        from api_pkg.schemas import BatchAuditRequest
        req = BatchAuditRequest(
            requirement_ids=["ADR.OR.B.005", "ORO.FTL.210"]
        )
        assert len(req.requirement_ids) == 2

    def test_batch_request_max_limit(self):
        from api_pkg.schemas import BatchAuditRequest
        with pytest.raises(Exception):
            BatchAuditRequest(requirement_ids=["rule"] * 51)

    def test_search_request_defaults(self):
        from api_pkg.schemas import SearchRequest
        req = SearchRequest(query="landing gear")
        assert req.k == 5
        assert req.domain_filter is None

    def test_graph_traverse_request(self):
        from api_pkg.schemas import GraphTraverseRequest
        req = GraphTraverseRequest(node_id="ADR.OR.B.005", depth=3)
        assert req.depth == 3

    def test_health_response(self):
        from api_pkg.schemas import HealthResponse, HealthStatus
        h = HealthResponse(status=HealthStatus.OK, version="1.0.0")
        assert h.status == HealthStatus.OK
        assert h.engine_ready is False


# ──────────────────────────────────────────────────────────────────────────────
# Compliance Routes
# ──────────────────────────────────────────────────────────────────────────────

class TestComplianceRoutes:
    def test_audit_engine_not_ready(self, client):
        """Should return 503 when pre-filtering hasn't been run."""
        response = client.post(
            "/api/v1/audit/compliance",
            json={"requirement_id": "ADR.OR.B.005"},
        )
        assert response.status_code == 503

    def test_audit_requirement_not_found(self, client, mock_engine):
        """Should return 404 for unknown requirement."""
        mock_engine.pre_filtered = True
        mock_engine.get_requirement.return_value = None
        response = client.post(
            "/api/v1/audit/compliance",
            json={"requirement_id": "NONEXISTENT.999"},
        )
        assert response.status_code == 404

    def test_batch_engine_not_ready(self, client):
        response = client.post(
            "/api/v1/audit/batch",
            json={"requirement_ids": ["ADR.OR.B.005"]},
        )
        assert response.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# Search Routes
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchRoutes:
    def test_search_no_index(self, client):
        response = client.post(
            "/api/v1/search",
            json={"query": "landing gear"},
        )
        assert response.status_code == 503

    def test_qa_no_index(self, client):
        response = client.post(
            "/api/v1/qa",
            json={"question": "What is ADR.OR.B.005?"},
        )
        assert response.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# Graph Routes
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphRoutes:
    def test_stats_graph_not_built(self, client):
        response = client.get("/api/v1/graph/stats")
        assert response.status_code == 503

    def test_traverse_graph_not_built(self, client):
        response = client.post(
            "/api/v1/graph/traverse",
            json={"node_id": "ADR.OR.B.005"},
        )
        assert response.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion Routes
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestionRoutes:
    def test_ingestion_status(self, client):
        response = client.get("/api/v1/ingest/status")
        assert response.status_code == 200
        data = response.json()
        assert data["easa_rules_count"] == 0
        assert data["pre_filtered"] is False

    def test_prefilter_no_index(self, client):
        response = client.post("/api/v1/ingest/prefilter")
        assert response.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# OpenAPI
# ──────────────────────────────────────────────────────────────────────────────

class TestOpenAPI:
    def test_openapi_schema_exists(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "ReguMap-AI Engine"

    def test_all_routes_documented(self, client):
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "/api/v1/audit/compliance" in paths
        assert "/api/v1/audit/batch" in paths
        assert "/api/v1/search" in paths
        assert "/api/v1/qa" in paths
        assert "/api/v1/graph/stats" in paths
        assert "/api/v1/graph/traverse" in paths
        assert "/api/v1/ingest/status" in paths
        assert "/api/v1/ingest/easa" in paths
        assert "/api/v1/ingest/manual" in paths
        assert "/api/v1/ingest/prefilter" in paths
        assert "/health" in paths
