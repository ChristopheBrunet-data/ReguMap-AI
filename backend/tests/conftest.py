"""
Shared pytest fixtures for ReguMap-AI test suite.
Provides mock objects, sample data factories, and test configuration.
"""

import os
import sys
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch

# Ensure project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import (
    EasaRequirement, ManualChunk, ComplianceAudit, AuditStatus,
    Alert, ComplianceTask, GraphNode, GraphEdge, GraphNodeType, EdgeType,
)


# ──────────────────────────────────────────────────────────────────────────────
# Factories
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_requirement() -> EasaRequirement:
    """Returns a realistic EASA requirement for testing."""
    return EasaRequirement(
        id="ADR.OR.B.005",
        text="The aerodrome operator shall establish and maintain a management system.",
        type="Implementing Rule",
        version="2026.1",
        source_title="Management System",
        domain="aerodromes",
        applicability_date="2026-01-01",
        amc_gm_info="Hard Law",
    )


@pytest.fixture
def sample_requirement_ftl() -> EasaRequirement:
    """Returns an FTL-related requirement."""
    return EasaRequirement(
        id="ORO.FTL.210",
        text="The maximum basic daily flight duty period shall be 13 hours.",
        type="Implementing Rule",
        version="2026.1",
        source_title="Flight times and duty periods",
        domain="air-ops",
        amc_gm_info="Hard Law",
    )


@pytest.fixture
def sample_amc_requirement() -> EasaRequirement:
    """Returns a Soft Law (AMC/GM) requirement."""
    return EasaRequirement(
        id="AMC1 ADR.OR.B.005",
        text="The management system should include risk-based compliance monitoring.",
        type="AMC",
        source_title="AMC1 ADR.OR.B.005 — Management System",
        domain="aerodromes",
        amc_gm_info="Soft Law",
    )


@pytest.fixture
def sample_manual_chunk() -> ManualChunk:
    """Returns a realistic manual chunk for testing."""
    return ManualChunk(
        page_number=42,
        section_title="4.1.1 Leadership Commitment",
        content="The Accountable Manager has full authority over safety management.",
        file_hash="abc123def456",
        has_diagram=False,
        diagram_path=None,
        bbox=None,
    )


@pytest.fixture
def sample_manual_chunk_with_diagram() -> ManualChunk:
    """Returns a manual chunk with visual evidence."""
    return ManualChunk(
        page_number=15,
        section_title="3.2 Emergency Procedures",
        content="Emergency evacuation flow diagram shows exit routes.",
        file_hash="abc123def456",
        has_diagram=True,
        diagram_path="data/evidence/page_15_img_0_abc123de.png",
        bbox=(10.0, 20.0, 500.0, 400.0),
    )


@pytest.fixture
def sample_rules_list(sample_requirement, sample_requirement_ftl, sample_amc_requirement):
    """Returns a list of mixed requirements for index building."""
    return [sample_requirement, sample_requirement_ftl, sample_amc_requirement]


@pytest.fixture
def sample_alert() -> Alert:
    """Returns a sample regulatory alert."""
    return Alert(
        feed_id="https://easa.europa.eu/alert/123",
        feed_source="easy_access_rules",
        title="Amendment to Part-ADR",
        summary="New requirements for aerodrome management systems.",
        link="https://easa.europa.eu/alert/123",
        published="2026-04-01T12:00:00",
        detected_at="2026-04-01T13:00:00",
        criticality="MEDIUM",
        rule_ids=["ADR.OR.B.005"],
        status="new",
        impact_analysis=None,
    )


@pytest.fixture
def sample_compliance_task() -> ComplianceTask:
    """Returns a sample compliance task."""
    return ComplianceTask(
        task_id="CT-ADR.OR.B.005-20260401120000",
        rule_id="ADR.OR.B.005",
        target_manual_section="Page 42, Section 4.1.1",
        suggested_change="Update management system documentation.",
        alert_feed_id="https://easa.europa.eu/alert/123",
        criticality="MEDIUM",
        status="Pending",
        created_at="2026-04-01T12:00:00",
    )


@pytest.fixture
def mock_api_key() -> str:
    return "test-api-key-fake-12345"


@pytest.fixture
def temp_dir():
    """Provides a temporary directory cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_easa_xml(temp_dir) -> str:
    """Creates a minimal EASA-style XML file for parser testing."""
    import xml.etree.ElementTree as ET

    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", w_ns)

    root = ET.Element("easy_access_rules", version="2026.1")

    # SDT content blocks
    sdt_content = {
        "101": "The operator shall establish flight time limitations. Max FDP: 13 hours.",
        "102": "The aerodrome operator shall maintain a safety management system.",
    }

    for sdt_id, text in sdt_content.items():
        sdt = ET.SubElement(root, f"{{{w_ns}}}sdt")
        sdt_pr = ET.SubElement(sdt, f"{{{w_ns}}}sdtPr")
        w_id = ET.SubElement(sdt_pr, f"{{{w_ns}}}id")
        w_id.set(f"{{{w_ns}}}val", sdt_id)
        t_elem = ET.SubElement(sdt, f"{{{w_ns}}}t")
        t_elem.text = text

    # Topic elements
    topics = [
        ("ORO.FTL.210", "Flight Time Limitations", "101", "air-ops"),
        ("ADR.OR.B.005", "Management System", "102", "aerodromes"),
    ]

    for rid, title, sid, dom in topics:
        topic = ET.SubElement(root, "topic")
        topic.set("ERulesId", rid)
        topic.set("source-title", title)
        topic.set("sdt-id", sid)
        topic.set("Domain", dom)

    xml_path = os.path.join(temp_dir, "test_easa.xml")
    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path


@pytest.fixture
def sample_manual_pdf(temp_dir) -> str:
    """Creates a minimal test PDF for parser testing."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 18)
    pdf.cell(0, 10, "4.1 Safety Management System", ln=True)
    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 10, (
        "The Accountable Manager maintains full authority over safety operations. "
        "The safety management system includes hazard identification, risk assessment, "
        "and safety assurance processes as required by applicable regulations."
    ))

    pdf_path = os.path.join(temp_dir, "test_manual.pdf")
    pdf.output(pdf_path)
    return pdf_path
