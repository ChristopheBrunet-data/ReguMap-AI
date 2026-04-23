"""
Tests for Pydantic schema models.
Validates field constraints, defaults, enums, and edge cases.
"""

import pytest
from schemas import (
    EasaRequirement, ManualChunk, ComplianceAudit, AuditStatus,
    Alert, ComplianceTask, GraphNode, GraphEdge, GraphNodeType, EdgeType,
)


class TestEasaRequirement:
    """Validates EasaRequirement model construction and constraints."""

    def test_minimal_construction(self):
        req = EasaRequirement(id="TEST.001", text="Some text", type="Rule")
        assert req.id == "TEST.001"
        assert req.version is None
        assert req.domain is None
        assert req.amc_gm_info is None

    def test_full_construction(self, sample_requirement):
        assert sample_requirement.id == "ADR.OR.B.005"
        assert sample_requirement.domain == "aerodromes"
        assert sample_requirement.amc_gm_info == "Hard Law"
        assert sample_requirement.applicability_date == "2026-01-01"

    def test_missing_required_field(self):
        with pytest.raises(Exception):
            EasaRequirement(id="TEST.001", type="Rule")  # missing text

    def test_empty_text(self):
        req = EasaRequirement(id="TEST.001", text="", type="Rule")
        assert req.text == ""


class TestManualChunk:
    """Validates ManualChunk model construction."""

    def test_minimal_construction(self):
        chunk = ManualChunk(
            page_number=1, section_title="Intro", content="Hello", file_hash="abc"
        )
        assert chunk.has_diagram is False
        assert chunk.diagram_path is None
        assert chunk.bbox is None

    def test_with_diagram(self, sample_manual_chunk_with_diagram):
        assert sample_manual_chunk_with_diagram.has_diagram is True
        assert sample_manual_chunk_with_diagram.diagram_path is not None
        assert len(sample_manual_chunk_with_diagram.bbox) == 4

    def test_page_number_type(self):
        chunk = ManualChunk(
            page_number=1, section_title="Test", content="x", file_hash="h"
        )
        assert isinstance(chunk.page_number, int)


class TestComplianceAudit:
    """Validates ComplianceAudit model and AuditStatus enum."""

    def test_enum_values(self):
        assert AuditStatus.COMPLIANT.value == "Compliant"
        assert AuditStatus.GAP.value == "Gap"
        assert AuditStatus.REQUIRES_HUMAN_REVIEW.value == "Requires Human Review"

    def test_construction_with_enum(self):
        audit = ComplianceAudit(
            requirement_id="ADR.OR.B.005",
            status=AuditStatus.COMPLIANT,
            evidence_quote="Test evidence",
            source_reference="Page 1",
            confidence_score=0.95,
        )
        assert audit.status == AuditStatus.COMPLIANT
        assert audit.cross_refs_used == []
        assert audit.validation_score is None

    def test_confidence_score_boundaries(self):
        audit_low = ComplianceAudit(
            requirement_id="TEST", status=AuditStatus.GAP,
            evidence_quote="None", source_reference="N/A",
            confidence_score=0.0,
        )
        audit_high = ComplianceAudit(
            requirement_id="TEST", status=AuditStatus.COMPLIANT,
            evidence_quote="Evidence", source_reference="Page 1",
            confidence_score=1.0,
        )
        assert audit_low.confidence_score == 0.0
        assert audit_high.confidence_score == 1.0

    def test_status_string_coercion(self):
        """AuditStatus is a str enum, so string values should work."""
        audit = ComplianceAudit(
            requirement_id="TEST", status="Compliant",
            evidence_quote="Test", source_reference="P1",
            confidence_score=0.9,
        )
        assert audit.status == AuditStatus.COMPLIANT


class TestAlert:
    """Validates Alert Pydantic model."""

    def test_construction(self, sample_alert):
        assert sample_alert.feed_id == "https://easa.europa.eu/alert/123"
        assert sample_alert.criticality == "MEDIUM"
        assert sample_alert.status == "new"
        assert sample_alert.impact_analysis is None

    def test_rule_ids_list(self, sample_alert):
        assert isinstance(sample_alert.rule_ids, list)
        assert "ADR.OR.B.005" in sample_alert.rule_ids


class TestComplianceTask:
    """Validates ComplianceTask Pydantic model."""

    def test_construction(self, sample_compliance_task):
        assert sample_compliance_task.status == "Pending"
        assert sample_compliance_task.implemented_at is None

    def test_missing_required_field(self):
        with pytest.raises(Exception):
            ComplianceTask(task_id="CT-1", rule_id="X")  # missing fields


class TestGraphModels:
    """Validates graph node and edge models."""

    def test_node_types(self):
        assert GraphNodeType.AGENCY.value == "Agency"
        assert GraphNodeType.REGULATION.value == "Regulation"
        assert GraphNodeType.AMC_GM.value == "AMC_GM"

    def test_edge_types(self):
        assert EdgeType.MANDATES.value == "MANDATES"
        assert EdgeType.CONFLICTS_WITH.value == "CONFLICTS_WITH"

    def test_graph_node_construction(self):
        node = GraphNode(
            id="ADR.OR.B.005", node_type=GraphNodeType.REGULATION,
            label="Management System",
        )
        assert node.properties == {}
        assert node.domain is None

    def test_graph_edge_construction(self):
        edge = GraphEdge(
            source="ADR.OR.B.005", target="AMC1 ADR.OR.B.005",
            edge_type=EdgeType.CLARIFIES,
        )
        assert edge.weight == 1.0
        assert edge.properties == {}
