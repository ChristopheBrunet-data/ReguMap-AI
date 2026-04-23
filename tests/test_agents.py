"""
Tests for the agentic compliance pipeline (agents.py).
Validates Pydantic model field access and structured output models.
"""

import pytest
from schemas import AuditStatus
from agents import (
    ResearchResult, ConflictResult, AuditResult, CriticResult,
)


class TestStructuredOutputModels:
    def test_research_result(self):
        r = ResearchResult(
            primary_rules=["ADR.OR.B.005"], noise_rules=["FOREWORD.001"],
            core_topic="Management System", cross_domain_links=[],
            regulatory_brief="Brief.", coverage_gaps=["No MEL"],
        )
        assert r.core_topic == "Management System"

    def test_audit_result_attribute_access(self):
        r = AuditResult(
            requirement_id="ADR.OR.B.005", status=AuditStatus.COMPLIANT,
            evidence_quote="The AM maintains authority.",
            source_reference="Page 42", confidence_score=0.92,
            cross_refs_used=["ORO.GEN.200"], visual_evidence_pages=[42],
        )
        assert r.requirement_id == "ADR.OR.B.005"
        assert r.status == AuditStatus.COMPLIANT
        assert r.confidence_score == 0.92
        assert r.suggested_fix is None

    def test_audit_result_mutation(self):
        r = AuditResult(
            requirement_id="TEST", status=AuditStatus.GAP,
            evidence_quote="original", source_reference="P1",
            confidence_score=0.5, cross_refs_used=[], visual_evidence_pages=[],
        )
        r.evidence_quote = "updated"
        r.source_reference = "P2"
        assert r.evidence_quote == "updated"

    def test_critic_result_attribute_access(self):
        r = CriticResult(
            validation_score=0.85, evidence_verified=True,
            citation_verified=True, status_justified=True,
            correct_citation=None, critique="OK.", suggested_fix_valid=True,
        )
        assert r.validation_score == 0.85
        assert r.correct_citation is None

    def test_critic_result_not_dict(self):
        r = CriticResult(
            validation_score=0.5, evidence_verified=False,
            citation_verified=False, status_justified=False, critique="Test",
        )
        with pytest.raises((TypeError, AttributeError)):
            _ = r["validation_score"]


class TestAssemblyLogic:
    def test_low_confidence_triggers_review(self):
        audit = AuditResult(
            requirement_id="T", status=AuditStatus.COMPLIANT,
            evidence_quote="E", source_reference="P1",
            confidence_score=0.3, cross_refs_used=[], visual_evidence_pages=[],
        )
        critic = CriticResult(
            validation_score=0.9, evidence_verified=True,
            citation_verified=True, status_justified=True, critique="OK",
        )
        final = audit.status
        if audit.confidence_score < 0.6 or critic.validation_score < 0.6:
            final = AuditStatus.REQUIRES_HUMAN_REVIEW
        assert final == AuditStatus.REQUIRES_HUMAN_REVIEW

    def test_high_scores_preserve_status(self):
        audit = AuditResult(
            requirement_id="T", status=AuditStatus.COMPLIANT,
            evidence_quote="E", source_reference="P1",
            confidence_score=0.95, cross_refs_used=[], visual_evidence_pages=[],
        )
        critic = CriticResult(
            validation_score=0.9, evidence_verified=True,
            citation_verified=True, status_justified=True, critique="Good",
        )
        final = audit.status
        if audit.confidence_score < 0.6 or critic.validation_score < 0.6:
            final = AuditStatus.REQUIRES_HUMAN_REVIEW
        assert final == AuditStatus.COMPLIANT

    def test_self_correction(self):
        audit = AuditResult(
            requirement_id="T", status=AuditStatus.PARTIAL,
            evidence_quote="E", source_reference="Wrong",
            confidence_score=0.8, cross_refs_used=[], visual_evidence_pages=[],
        )
        critic = CriticResult(
            validation_score=0.7, evidence_verified=True,
            citation_verified=False, status_justified=True,
            correct_citation="Page 42", critique="Wrong citation.",
        )
        if critic.correct_citation and not critic.citation_verified:
            audit.source_reference = critic.correct_citation
        assert audit.source_reference == "Page 42"
