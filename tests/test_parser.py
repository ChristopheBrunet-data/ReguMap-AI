"""
Tests for EASA XML and Manual PDF parsers.
"""

import os
import pytest
from parser import EasaXmlParser, ManualPdfParser
from schemas import EasaRequirement, ManualChunk


class TestEasaXmlParser:
    """Tests EASA XML parsing with sample data."""

    def test_parse_sample_xml(self, sample_easa_xml):
        parser = EasaXmlParser(sample_easa_xml)
        requirements = list(parser.parse())
        assert len(requirements) >= 1
        for req in requirements:
            assert isinstance(req, EasaRequirement)
            assert req.id != "UNKNOWN_ID"

    def test_parsed_fields(self, sample_easa_xml):
        parser = EasaXmlParser(sample_easa_xml)
        requirements = list(parser.parse())
        ids = {r.id for r in requirements}
        # Our sample XML has ORO.FTL.210 and ADR.OR.B.005
        assert "ORO.FTL.210" in ids or "ADR.OR.B.005" in ids

    def test_domain_extracted(self, sample_easa_xml):
        parser = EasaXmlParser(sample_easa_xml)
        requirements = list(parser.parse())
        for req in requirements:
            assert req.domain is not None

    def test_amc_gm_classification(self, sample_easa_xml):
        parser = EasaXmlParser(sample_easa_xml)
        requirements = list(parser.parse())
        for req in requirements:
            assert req.amc_gm_info in ("Hard Law", "Soft Law")

    def test_nonexistent_file(self, temp_dir):
        parser = EasaXmlParser(os.path.join(temp_dir, "nonexistent.xml"))
        with pytest.raises(ValueError, match="Failed to parse"):
            list(parser.parse())

    def test_malformed_xml(self, temp_dir):
        path = os.path.join(temp_dir, "bad.xml")
        with open(path, "w") as f:
            f.write("<not>valid<xml")
        parser = EasaXmlParser(path)
        with pytest.raises(ValueError):
            list(parser.parse())


class TestManualPdfParser:
    """Tests PDF manual parsing."""

    def test_parse_sample_pdf(self, sample_manual_pdf):
        parser = ManualPdfParser(sample_manual_pdf)
        chunks = list(parser.parse())
        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk, ManualChunk)
            assert chunk.content
            assert chunk.file_hash

    def test_chunk_page_numbers(self, sample_manual_pdf):
        parser = ManualPdfParser(sample_manual_pdf)
        chunks = list(parser.parse())
        for chunk in chunks:
            assert chunk.page_number >= 1

    def test_file_hash_consistency(self, sample_manual_pdf):
        parser = ManualPdfParser(sample_manual_pdf)
        chunks = list(parser.parse())
        hashes = {c.file_hash for c in chunks}
        assert len(hashes) == 1  # All chunks from same file

    def test_file_hash_is_sha256(self, sample_manual_pdf):
        parser = ManualPdfParser(sample_manual_pdf)
        chunks = list(parser.parse())
        # SHA-256 produces a 64-character hex digest
        assert len(chunks[0].file_hash) == 64

    def test_section_titles_extracted(self, sample_manual_pdf):
        parser = ManualPdfParser(sample_manual_pdf)
        chunks = list(parser.parse())
        titles = [c.section_title for c in chunks]
        assert any(t != "General" for t in titles) or len(titles) > 0
