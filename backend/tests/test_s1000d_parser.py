"""
Tests for the S1000D deterministic parser.
Validates: identification extraction, effectivity parsing, content conversion,
Markdown output, chunking, and evidence coordinates.
"""

import os
import pytest
from ingestion.s1000d_parser import S1000DParser
from ingestion.contracts import DocumentSource


# Path to the sample S1000D XML in project root
SAMPLE_S1000D = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sample_s1000d.xml",
)


class TestS1000DParserIdentification:
    """Tests identification extraction from <identAndStatusSection>."""

    def test_parse_returns_result(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        assert result.is_success()
        assert result.source_type == DocumentSource.S1000D_XML

    def test_dmc_extraction(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.dmc != "UNKNOWN"
        assert "A320" in dm.identification.dmc
        assert "32" in dm.identification.dmc

    def test_model_ident_code(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.model_ident_code == "A320"

    def test_system_code(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.system_code == "32"  # Landing gear

    def test_info_code(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.info_code == "520"  # Removal procedure

    def test_tech_name(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert "landing gear" in dm.identification.tech_name.lower()

    def test_info_name(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.info_name is not None
        assert "removal" in dm.identification.info_name.lower()

    def test_issue_info(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.issue_number == "003"
        assert dm.identification.in_work == "01"

    def test_issue_date(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.issue_date is not None
        assert dm.identification.issue_date.year == 2026

    def test_language(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert dm.identification.language == "en"


class TestS1000DParserEffectivity:
    """Tests effectivity / applicability extraction."""

    def test_msn_list_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        eff = dm.effectivity
        assert len(eff.msn_list) > 0
        assert "1001" in eff.msn_list

    def test_fleet_types_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        eff = dm.effectivity
        assert len(eff.fleet_types) > 0
        assert "A320-214" in eff.fleet_types

    def test_serial_range_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        eff = dm.effectivity
        assert eff.serial_range_start == "1001"
        assert eff.serial_range_end == "1050"

    def test_effectivity_separation(self):
        """Effectivity must be separated from content (key requirement)."""
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        # Content should NOT contain raw effectivity data
        assert "applicPropertyIdent" not in dm.content_markdown
        # But effectivity object should have the data
        assert len(dm.effectivity.msn_list) > 0

    def test_effectivity_on_chunks(self):
        """Every chunk should carry the effectivity MSNs."""
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        for chunk in result.chunks:
            assert isinstance(chunk.effectivity_msns, list)
            if result.data_modules[0].effectivity.msn_list:
                assert len(chunk.effectivity_msns) > 0


class TestS1000DParserContent:
    """Tests content extraction and Markdown conversion."""

    def test_markdown_not_empty(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert len(dm.content_markdown) > 100

    def test_warnings_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert len(dm.warnings) >= 2
        assert any("hydraulic" in w.lower() for w in dm.warnings)

    def test_cautions_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert len(dm.cautions) >= 1

    def test_dm_references_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert len(dm.dm_references) >= 2  # prelim + close refs

    def test_figure_references_extracted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert len(dm.figure_references) >= 1
        assert any("ICN" in ref for ref in dm.figure_references)

    def test_markdown_has_headers(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert "# " in dm.content_markdown  # H1 or H2

    def test_markdown_has_numbered_steps(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert "1." in dm.content_markdown
        assert "2." in dm.content_markdown

    def test_markdown_has_warnings_formatted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert "⚠️ **WARNING**" in dm.content_markdown

    def test_markdown_has_cautions_formatted(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert "⚡ **CAUTION**" in dm.content_markdown

    def test_content_is_clean_markdown(self):
        """Content should be clean markdown, no raw XML tags."""
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        dm = result.data_modules[0]
        assert "<proceduralStep>" not in dm.content_markdown
        assert "<para>" not in dm.content_markdown
        assert "<warning>" not in dm.content_markdown


class TestS1000DParserChunking:
    """Tests chunk generation from parsed data modules."""

    def test_chunks_produced(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        assert result.total_chunks >= 1

    def test_chunks_have_evidence(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        for chunk in result.chunks:
            assert chunk.evidence is not None
            assert chunk.evidence.source_type == DocumentSource.S1000D_XML
            assert chunk.evidence.dmc is not None

    def test_chunks_have_embedding_text(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        for chunk in result.chunks:
            assert len(chunk.embedding_text) > 0
            # Embedding text should NOT have markdown syntax
            assert "##" not in chunk.embedding_text

    def test_chunks_have_source_hash(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        for chunk in result.chunks:
            assert len(chunk.source_hash) == 64  # SHA-256

    def test_chunk_ids_deterministic(self):
        """Same file should produce same chunk IDs."""
        parser1 = S1000DParser(SAMPLE_S1000D)
        parser2 = S1000DParser(SAMPLE_S1000D)
        result1 = parser1.parse()
        result2 = parser2.parse()
        ids1 = [c.chunk_id for c in result1.chunks]
        ids2 = [c.chunk_id for c in result2.chunks]
        assert ids1 == ids2

    def test_chunk_word_count(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        for chunk in result.chunks:
            assert chunk.word_count > 0


class TestS1000DParserErrorHandling:
    """Tests error handling for malformed/missing files."""

    def test_missing_file(self):
        parser = S1000DParser("nonexistent_file.xml")
        result = parser.parse()
        assert not result.is_success()
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_malformed_xml(self, temp_dir):
        path = os.path.join(temp_dir, "bad.xml")
        with open(path, "w") as f:
            f.write("<not>valid<xml")
        parser = S1000DParser(path)
        result = parser.parse()
        assert not result.is_success()
        assert any("parse error" in e.lower() for e in result.errors)

    def test_xml_without_dmodule(self, temp_dir):
        path = os.path.join(temp_dir, "empty.xml")
        with open(path, "w") as f:
            f.write('<?xml version="1.0"?><root><data>test</data></root>')
        parser = S1000DParser(path)
        result = parser.parse()
        assert not result.is_success()
        assert any("dmodule" in e.lower() for e in result.errors)

    def test_source_hash_computed(self):
        parser = S1000DParser(SAMPLE_S1000D)
        result = parser.parse()
        assert len(result.source_hash) == 64  # SHA-256
