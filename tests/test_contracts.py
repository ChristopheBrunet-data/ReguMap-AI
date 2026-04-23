"""
Tests for ingestion pipeline data contracts.
Validates Pydantic models, enums, evidence coordinates, and effectivity matching.
"""

import pytest
from ingestion.contracts import (
    DocumentSource, ManualType, LawType, S1000DInfoCode,
    EvidenceCoordinate, IngestedChunk, S1000DIdentification,
    S1000DEffectivity, S1000DDataModule, FleetConfig,
    IngestionResult,
)
from datetime import date


class TestEnums:
    """Validates all contract enums."""

    def test_document_source_values(self):
        assert DocumentSource.PDF.value == "PDF"
        assert DocumentSource.S1000D_XML.value == "S1000D_XML"
        assert DocumentSource.EASA_XML.value == "EASA_XML"

    def test_manual_type_values(self):
        assert ManualType.OM_A.value == "OM-A"
        assert ManualType.CAME.value == "CAME"
        assert ManualType.MOE.value == "MOE"
        assert ManualType.AMM.value == "AMM"
        assert ManualType.IPC.value == "IPC"

    def test_law_type_values(self):
        assert LawType.HARD_LAW.value == "Hard Law"
        assert LawType.SOFT_LAW.value == "Soft Law"

    def test_info_code_values(self):
        assert S1000DInfoCode.PROCEDURE.value == "520"
        assert S1000DInfoCode.DESCRIPTION.value == "040"
        assert S1000DInfoCode.FAULT_ISOLATION.value == "300"


class TestEvidenceCoordinate:
    """Validates the evidence-first coordinate system."""

    def test_pdf_coordinate(self):
        coord = EvidenceCoordinate(
            source_type=DocumentSource.PDF,
            document_id="abc123",
            page=42,
            paragraph_id="4.1.2",
            section_title="Safety Policy",
        )
        citation = coord.citation_string()
        assert "Page 42" in citation
        assert "§4.1.2" in citation
        assert "Safety Policy" in citation

    def test_s1000d_coordinate(self):
        coord = EvidenceCoordinate(
            source_type=DocumentSource.S1000D_XML,
            document_id="A320-32-00-00-00AA-520A-A",
            dmc="A320-32-00-00-00AA-520A-A",
            step_path="mainProcedure/step[3]/step[1]",
        )
        citation = coord.citation_string()
        assert "DMC A320-32-00-00-00AA-520A-A" in citation
        assert "Step mainProcedure/step[3]/step[1]" in citation

    def test_easa_coordinate(self):
        coord = EvidenceCoordinate(
            source_type=DocumentSource.EASA_XML,
            document_id="ADR.OR.B.005",
            erules_id="ADR.OR.B.005",
        )
        citation = coord.citation_string()
        assert "Rule ADR.OR.B.005" in citation

    def test_minimal_coordinate(self):
        coord = EvidenceCoordinate(
            source_type=DocumentSource.MANUAL,
            document_id="doc123",
        )
        citation = coord.citation_string()
        assert "MANUAL" in citation
        assert "doc123" in citation


class TestIngestedChunk:
    """Validates universal chunk construction."""

    def test_construction(self):
        evidence = EvidenceCoordinate(
            source_type=DocumentSource.S1000D_XML,
            document_id="DMC-TEST",
            dmc="DMC-TEST",
        )
        chunk = IngestedChunk(
            chunk_id="abc123",
            content_markdown="## Step 1\nDo something.",
            embedding_text="Step 1 Do something.",
            evidence=evidence,
            source_hash="sha256hash",
            source_type=DocumentSource.S1000D_XML,
            word_count=4,
        )
        assert chunk.chunk_id == "abc123"
        assert chunk.effectivity_msns == []
        assert chunk.has_visual is False

    def test_generate_chunk_id_deterministic(self):
        id1 = IngestedChunk.generate_chunk_id("doc1", "section1")
        id2 = IngestedChunk.generate_chunk_id("doc1", "section1")
        assert id1 == id2
        assert len(id1) == 16

    def test_generate_chunk_id_unique(self):
        id1 = IngestedChunk.generate_chunk_id("doc1", "section1")
        id2 = IngestedChunk.generate_chunk_id("doc1", "section2")
        assert id1 != id2

    def test_with_effectivity(self):
        evidence = EvidenceCoordinate(
            source_type=DocumentSource.S1000D_XML,
            document_id="DMC",
            dmc="DMC",
        )
        chunk = IngestedChunk(
            chunk_id="test",
            content_markdown="content",
            embedding_text="content",
            evidence=evidence,
            source_hash="hash",
            source_type=DocumentSource.S1000D_XML,
            effectivity_msns=["1001", "1005", "1010"],
            effectivity_fleet="A320-214",
        )
        assert len(chunk.effectivity_msns) == 3
        assert chunk.effectivity_fleet == "A320-214"


class TestS1000DIdentification:
    """Validates S1000D identification extraction."""

    def test_construction(self):
        ident = S1000DIdentification(
            dmc="A320-32-00-00-00AA-520A-A",
            model_ident_code="A320",
            system_code="32",
            info_code="520",
            tech_name="Main landing gear",
            info_name="Removal",
            issue_date=date(2026, 3, 15),
        )
        assert ident.dmc == "A320-32-00-00-00AA-520A-A"
        assert ident.system_code == "32"
        assert ident.issue_date == date(2026, 3, 15)

    def test_defaults(self):
        ident = S1000DIdentification(
            dmc="TEST", model_ident_code="T", system_code="00",
            info_code="040", tech_name="Test",
        )
        assert ident.issue_number == "001"
        assert ident.in_work == "00"
        assert ident.language == "en"
        assert ident.country == "US"


class TestS1000DEffectivity:
    """Validates effectivity/applicability matching logic."""

    def test_matches_specific_msn(self):
        eff = S1000DEffectivity(msn_list=["1001", "1005", "1010"])
        assert eff.matches_msn("1001") is True
        assert eff.matches_msn("1005") is True
        assert eff.matches_msn("9999") is False

    def test_matches_all(self):
        eff = S1000DEffectivity(applies_to_all=True)
        assert eff.matches_msn("anything") is True

    def test_matches_serial_range(self):
        eff = S1000DEffectivity(
            serial_range_start="1001", serial_range_end="1050"
        )
        assert eff.matches_msn("1025") is True
        assert eff.matches_msn("0999") is False
        assert eff.matches_msn("1051") is False

    def test_empty_means_all(self):
        eff = S1000DEffectivity()
        assert eff.matches_msn("1234") is True

    def test_fleet_types_stored(self):
        eff = S1000DEffectivity(fleet_types=["A320-214", "A320-232"])
        assert "A320-214" in eff.fleet_types
        assert len(eff.fleet_types) == 2


class TestFleetConfig:
    """Validates fleet configuration."""

    def test_construction(self):
        fleet = FleetConfig(
            fleet_type="A320-214",
            manufacturer="Airbus",
            type_certificate="EASA.A.064",
            msn_list=["1001", "1005"],
            registration_map={"1001": "F-GKXO", "1005": "F-GKXP"},
        )
        assert fleet.fleet_type == "A320-214"
        assert fleet.registration_map["1001"] == "F-GKXO"


class TestIngestionResult:
    """Validates batch ingestion result."""

    def test_success(self):
        result = IngestionResult(
            source_path="test.xml",
            source_type=DocumentSource.S1000D_XML,
            source_hash="hash",
            total_chunks=5,
        )
        assert result.is_success() is True

    def test_failure(self):
        result = IngestionResult(
            source_path="test.xml",
            source_type=DocumentSource.S1000D_XML,
            source_hash="hash",
            errors=["File not found"],
        )
        assert result.is_success() is False
