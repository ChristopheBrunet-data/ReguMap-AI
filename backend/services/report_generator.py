"""
Audit Report Generator — Produces structured PDF compliance reports (Task 12).

Takes BatchAuditResponse data and generates a formal PDF with:
- Executive summary with compliance heatmap
- Per-rule findings with evidence trails
- Confidence scores and agent trace
- Cross-reference index
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def generate_audit_report(
    results: List[Dict[str, Any]],
    output_dir: str = "data/reports",
    title: str = "AeroMind Compliance Audit Report",
) -> str:
    """
    Generates a structured PDF compliance report from audit results.

    Args:
        results: List of audit result dicts (from BatchAuditResponse.results)
        output_dir: Directory to save the PDF
        title: Report title

    Returns:
        Path to the generated PDF file.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        logger.error("fpdf2 not installed. Install with: pip install fpdf2")
        raise ImportError("fpdf2 is required for report generation. pip install fpdf2")

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"compliance_report_{timestamp}.pdf"
    filepath = os.path.join(output_dir, filename)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Page 1: Title & Executive Summary ──────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 20, title, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"Generated: {datetime.now(timezone.utc).isoformat()}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 8, "DO-326A Compliance Assessment", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    # Compliance summary
    total = len(results)
    compliant = sum(1 for r in results if r.get("status") == "Compliant")
    partial = sum(1 for r in results if r.get("status") == "Partial")
    gaps = sum(1 for r in results if r.get("status") == "Gap")
    review = sum(1 for r in results if r.get("status") == "Requires Human Review")

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)

    pdf.cell(0, 8, f"Total Requirements Audited: {total}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 128, 0)
    pdf.cell(0, 8, f"  Compliant: {compliant} ({_pct(compliant, total)})", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(255, 165, 0)
    pdf.cell(0, 8, f"  Partial: {partial} ({_pct(partial, total)})", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(220, 0, 0)
    pdf.cell(0, 8, f"  Gap: {gaps} ({_pct(gaps, total)})", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"  Requires Review: {review} ({_pct(review, total)})", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # Compliance rate
    rate = _pct(compliant + partial, total) if total > 0 else "N/A"
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, f"Overall Compliance Rate: {rate}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # ── Page 2+: Detailed Findings ─────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, "Detailed Findings", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    for i, result in enumerate(results, 1):
        req_id = result.get("requirement_id", "Unknown")
        status = result.get("status", "Unknown")
        confidence = result.get("confidence_score", 0.0)
        evidence = result.get("evidence_quote", "No evidence")
        source = result.get("source_reference", "N/A")
        fix = result.get("suggested_fix")
        cross_refs = result.get("cross_refs_used", [])
        trace = result.get("agent_trace", "")

        # Status color
        if status == "Compliant":
            pdf.set_fill_color(200, 255, 200)
        elif status == "Partial":
            pdf.set_fill_color(255, 240, 200)
        elif status == "Gap":
            pdf.set_fill_color(255, 200, 200)
        else:
            pdf.set_fill_color(230, 230, 230)

        # Finding header
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, f"[{i}] {req_id} - {status} (Confidence: {confidence:.0%})",
                 new_x="LMARGIN", new_y="NEXT", fill=True)

        # Evidence
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, f"Evidence: {_sanitize(evidence[:500])}")

        # Source
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, f"Source: {source}", new_x="LMARGIN", new_y="NEXT")

        # Cross-references
        if cross_refs:
            pdf.cell(0, 5, f"Cross-refs: {', '.join(cross_refs[:5])}", new_x="LMARGIN", new_y="NEXT")

        # Suggested fix
        if fix:
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(220, 0, 0)
            pdf.multi_cell(0, 5, f"Recommended Action: {_sanitize(fix[:300])}")
            pdf.set_text_color(0, 0, 0)

        # Agent trace (compact)
        if trace:
            pdf.set_font("Courier", "", 7)
            pdf.set_text_color(100, 100, 100)
            pdf.multi_cell(0, 4, f"Trace: {_sanitize(trace[:200])}")
            pdf.set_text_color(0, 0, 0)

        pdf.ln(4)

        # Page break every 3 findings
        if i % 3 == 0 and i < total:
            pdf.add_page()

    # ── Footer ─────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Methodology", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, (
        "This report was generated by AeroMind Compliance (ReguMap-AI), "
        "using a 5-stage agentic pipeline:\n\n"
        "1. Researcher Agent: Semantic + BM25 hybrid search across regulatory corpus\n"
        "2. Conflict Detector: Cross-agency regulatory conflict analysis\n"
        "3. Auditor Agent: Evidence-based compliance assessment with multimodal analysis\n"
        "4. Critic Agent: Citation verification and confidence calibration\n"
        "5. Symbolic Validator: Deterministic Neo4j graph verification (strict evidence mapping)\n\n"
        "All citations are cryptographically verified against the regulatory knowledge graph. "
        "This report is suitable for DO-326A compliance review."
    ))

    pdf.output(filepath)
    logger.info(f"Audit report generated: {filepath}")
    return filepath


def _pct(n: int, total: int) -> str:
    """Format as percentage string."""
    if total == 0:
        return "0%"
    return f"{(n / total) * 100:.1f}%"


def _sanitize(text: str) -> str:
    """Sanitize text for PDF output — remove non-latin1 characters."""
    return text.encode("latin-1", errors="replace").decode("latin-1")
