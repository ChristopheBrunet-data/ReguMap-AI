"""
S1000D Deterministic Parser — Extracts Data Modules from S1000D XML files.

Zero LLM dependency. Fully deterministic. Produces typed Pydantic contracts
(S1000DDataModule, IngestedChunk) with evidence coordinates for every piece
of extracted content.

Supports S1000D Issue 4.1+ / 5.0 XML structure:
    <dmodule>
      <identAndStatusSection>  →  S1000DIdentification + S1000DEffectivity
      <content>
        <procedure>            →  Markdown + IngestedChunks with step paths
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import date
from typing import Generator, List, Optional, Tuple

from lxml import etree

from ingestion.hasher import generate_node_hash

from ingestion.contracts import (
    DocumentSource,
    EvidenceCoordinate,
    IngestedChunk,
    IngestionResult,
    S1000DDataModule,
    S1000DEffectivity,
    S1000DIdentification,
    RegulatoryNode
)
from ingestion.markdown_converter import (
    _build_dmc_from_element,
    convert_close_rqmts,
    convert_dm_ref,
    convert_preliminary_rqmts,
    convert_procedural_steps,
    element_text,
)

logger = logging.getLogger(__name__)


class S1000DParser:
    """
    Deterministic parser for S1000D XML Data Modules.

    Usage:
        parser = S1000DParser("path/to/datamodule.xml")
        result = parser.parse()
        for chunk in result.chunks:
            print(chunk.evidence.citation_string())
    """

    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self._source_hash: Optional[str] = None

    @property
    def source_hash(self) -> str:
        """Lazy-computed SHA-256 hash of the source file."""
        if self._source_hash is None:
            hasher = hashlib.sha256()
            with open(self.xml_path, "rb") as f:
                for block in iter(lambda: f.read(8192), b""):
                    hasher.update(block)
            self._source_hash = hasher.hexdigest()
        return self._source_hash

    def parse(self) -> IngestionResult:
        """
        Parse the S1000D XML file and return an IngestionResult.

        This is the main entry point. It:
        1. Validates the XML structure
        2. Extracts identification + effectivity metadata
        3. Converts content to Markdown
        4. Produces IngestedChunks with evidence coordinates
        """
        start_time = time.time()
        errors: List[str] = []

        if not os.path.exists(self.xml_path):
            return IngestionResult(
                source_path=self.xml_path,
                source_type=DocumentSource.S1000D_XML,
                source_hash="",
                errors=[f"File not found: {self.xml_path}"],
            )

        try:
            tree = etree.parse(self.xml_path)
        except etree.XMLSyntaxError as e:
            return IngestionResult(
                source_path=self.xml_path,
                source_type=DocumentSource.S1000D_XML,
                source_hash="",
                errors=[f"XML parse error: {e}"],
            )

        root = tree.getroot()
        dmodule = root if root.tag == "dmodule" else root.find(".//dmodule")
        if dmodule is None:
            return IngestionResult(
                source_path=self.xml_path,
                source_type=DocumentSource.S1000D_XML,
                source_hash=self.source_hash,
                errors=["No <dmodule> element found in XML"],
            )

        # ── Extract identification ────────────────────────────────────────
        ident, ident_errors = self._parse_identification(dmodule)
        errors.extend(ident_errors)

        # ── Extract effectivity ───────────────────────────────────────────
        effectivity = self._parse_effectivity(dmodule)

        # ── Extract content ───────────────────────────────────────────────
        content_md, warnings, cautions, notes, dm_refs, fig_refs, content_errors = (
            self._parse_content(dmodule)
        )
        errors.extend(content_errors)

        # ── Build the data module ─────────────────────────────────────────
        data_module = S1000DDataModule(
            identification=ident,
            effectivity=effectivity,
            content_markdown=content_md,
            warnings=warnings,
            cautions=cautions,
            notes=notes,
            dm_references=dm_refs,
            figure_references=fig_refs,
            source_hash=self.source_hash,
            raw_xml_path=self.xml_path,
        )

        # ── Chunk the content ─────────────────────────────────────────────
        chunks = self._create_chunks(data_module)

        duration = time.time() - start_time
        logger.info(
            f"Parsed S1000D module {ident.dmc}: "
            f"{len(chunks)} chunks, {len(warnings)} warnings, "
            f"{len(dm_refs)} DM refs in {duration:.2f}s"
        )

        return IngestionResult(
            source_path=self.xml_path,
            source_type=DocumentSource.S1000D_XML,
            source_hash=self.source_hash,
            chunks=chunks,
            data_modules=[data_module],
            total_chunks=len(chunks),
            warnings_extracted=len(warnings),
            duration_seconds=round(duration, 3),
            errors=errors,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Identification Extraction
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_identification(
        self, dmodule: etree._Element
    ) -> Tuple[S1000DIdentification, List[str]]:
        """Extract <identAndStatusSection> into S1000DIdentification."""
        errors: List[str] = []
        ident_section = dmodule.find(".//identAndStatusSection")

        dm_code = dmodule.find(".//dmCode")
        if dm_code is None:
            errors.append("Missing <dmCode> element")
            return S1000DIdentification(
                dmc="UNKNOWN",
                model_ident_code="UNKNOWN",
                system_code="00",
                info_code="000",
                tech_name="Unknown",
            ), errors

        dmc = _build_dmc_from_element(dm_code)

        # Issue info
        issue_info = dmodule.find(".//issueInfo")
        issue_number = issue_info.get("issueNumber", "001") if issue_info is not None else "001"
        in_work = issue_info.get("inWork", "00") if issue_info is not None else "00"

        # Issue date
        issue_date_el = dmodule.find(".//issueDate")
        issue_date = None
        if issue_date_el is not None:
            try:
                issue_date = date(
                    int(issue_date_el.get("year", "2026")),
                    int(issue_date_el.get("month", "1")),
                    int(issue_date_el.get("day", "1")),
                )
            except (ValueError, TypeError):
                errors.append("Invalid issue date")

        # Language
        lang_el = dmodule.find(".//language")
        language = lang_el.get("languageIsoCode", "en") if lang_el is not None else "en"
        country = lang_el.get("countryIsoCode", "US") if lang_el is not None else "US"

        # Title
        title_el = dmodule.find(".//dmTitle")
        tech_name = ""
        info_name = None
        if title_el is not None:
            tn = title_el.find("techName")
            inn = title_el.find("infoName")
            tech_name = element_text(tn) if tn is not None else ""
            info_name = element_text(inn) if inn is not None else None

        return S1000DIdentification(
            dmc=dmc,
            model_ident_code=dm_code.get("modelIdentCode", ""),
            system_code=dm_code.get("systemCode", ""),
            sub_system_code=dm_code.get("subSystemCode"),
            assy_code=dm_code.get("assyCode"),
            info_code=dm_code.get("infoCode", ""),
            tech_name=tech_name,
            info_name=info_name,
            issue_number=issue_number,
            in_work=in_work,
            issue_date=issue_date,
            language=language,
            country=country,
        ), errors

    # ──────────────────────────────────────────────────────────────────────────
    # Effectivity Extraction
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_effectivity(self, dmodule: etree._Element) -> S1000DEffectivity:
        """Extract applicability/effectivity from <dmStatus><applic>."""
        msn_list: List[str] = []
        fleet_types: List[str] = []
        serial_start: Optional[str] = None
        serial_end: Optional[str] = None

        for assign in dmodule.findall(".//applic//assign"):
            prop_ident = assign.get("applicPropertyIdent", "")
            prop_values = assign.get("applicPropertyValues", "")

            if prop_ident == "MSN" and prop_values:
                msn_list = [v.strip() for v in prop_values.split() if v.strip()]
            elif prop_ident == "FleetType" and prop_values:
                fleet_types = [v.strip() for v in prop_values.split() if v.strip()]
            elif prop_ident == "SerialRange" and prop_values:
                parts = prop_values.split("-")
                if len(parts) == 2:
                    serial_start = parts[0].strip()
                    serial_end = parts[1].strip()

        applies_to_all = not msn_list and not fleet_types and not serial_start

        return S1000DEffectivity(
            msn_list=msn_list,
            fleet_types=fleet_types,
            serial_range_start=serial_start,
            serial_range_end=serial_end,
            applies_to_all=applies_to_all,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Content Extraction
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_content(
        self, dmodule: etree._Element
    ) -> Tuple[str, List[str], List[str], List[str], List[str], List[str], List[str]]:
        """
        Extract <content> and convert to Markdown.

        Returns:
            (content_markdown, warnings, cautions, notes, dm_references,
             figure_references, errors)
        """
        errors: List[str] = []
        all_lines: List[str] = []
        all_warnings: List[str] = []
        all_cautions: List[str] = []
        all_notes: List[str] = []
        all_dm_refs: List[str] = []
        all_fig_refs: List[str] = []

        content = dmodule.find(".//content")
        if content is None:
            errors.append("No <content> element found")
            return "", [], [], [], [], [], errors

        procedure = content.find("procedure")
        if procedure is None:
            # Non-procedural module — extract all text
            text = element_text(content)
            all_lines.append(text)
            return "\n\n".join(all_lines), [], [], [], [], [], errors

        # ── Title ─────────────────────────────────────────────────────────
        title_el = dmodule.find(".//dmTitle")
        if title_el is not None:
            tn = title_el.find("techName")
            inn = title_el.find("infoName")
            tech = element_text(tn) if tn is not None else ""
            info = element_text(inn) if inn is not None else ""
            title = f"{tech} — {info}".strip(" —") if tech else "Procedure"
            all_lines.append(f"# {title}")
            all_lines.append("")

        # ── Preliminary Requirements ──────────────────────────────────────
        prelim = procedure.find("preliminaryRqmts")
        if prelim is not None:
            all_lines.append("## Prerequisites")
            all_lines.append("")
            p_lines, p_refs, p_warnings, p_cautions, _ = convert_preliminary_rqmts(prelim)
            all_lines.extend(p_lines)
            all_dm_refs.extend(p_refs)
            all_warnings.extend(p_warnings)
            all_cautions.extend(p_cautions)
            all_lines.append("")

        # ── Main Procedure ────────────────────────────────────────────────
        main_proc = procedure.find("mainProcedure")
        if main_proc is not None:
            all_lines.append("## Procedure")
            all_lines.append("")
            step_lines, step_w, step_c, step_n = convert_procedural_steps(main_proc)
            all_lines.extend(step_lines)
            all_warnings.extend(step_w)
            all_cautions.extend(step_c)
            all_notes.extend(step_n)
            all_lines.append("")

            # Extract figure references from main procedure
            for fig in main_proc.findall(".//figure"):
                graphic = fig.find(".//graphic")
                if graphic is not None:
                    fig_id = graphic.get("infoEntityIdent", "")
                    if fig_id:
                        all_fig_refs.append(fig_id)

            # Extract inline DM references
            for dm_ref in main_proc.findall(".//dmRef"):
                _, dmc = convert_dm_ref(dm_ref)
                if dmc:
                    all_dm_refs.append(dmc)

        # ── Close Requirements ────────────────────────────────────────────
        close = procedure.find("closeRqmts")
        if close is not None:
            all_lines.append("## Follow-up Actions")
            all_lines.append("")
            c_lines, c_refs = convert_close_rqmts(close)
            all_lines.extend(c_lines)
            all_dm_refs.extend(c_refs)

        content_md = "\n".join(all_lines)

        # Deduplicate
        all_dm_refs = list(dict.fromkeys(all_dm_refs))
        all_fig_refs = list(dict.fromkeys(all_fig_refs))

        return content_md, all_warnings, all_cautions, all_notes, all_dm_refs, all_fig_refs, errors

    # ──────────────────────────────────────────────────────────────────────────
    # Chunking
    # ──────────────────────────────────────────────────────────────────────────

    def _create_chunks(self, dm: S1000DDataModule) -> List[IngestedChunk]:
        """
        Create IngestedChunks from a parsed S1000DDataModule.

        Strategy: One chunk per top-level section (Prerequisites, Procedure,
        Follow-up). Each chunk carries the full effectivity and evidence
        coordinate.
        """
        chunks: List[IngestedChunk] = []
        dmc = dm.identification.dmc
        title = f"{dm.identification.tech_name} — {dm.identification.info_name or 'Procedure'}"

        # Split content by ## headers for section-level chunking
        sections = self._split_by_headers(dm.content_markdown)

        for section_title, section_content in sections:
            if not section_content.strip():
                continue

            # Build evidence coordinate
            evidence = EvidenceCoordinate(
                source_type=DocumentSource.S1000D_XML,
                document_id=dmc,
                dmc=dmc,
                section_title=section_title or title,
                paragraph_id=section_title,
            )

            # Generate embedding text (strip markdown syntax)
            embedding_text = self._strip_markdown(section_content)
            word_count = len(embedding_text.split())

            chunk_id = IngestedChunk.generate_chunk_id(
                dmc, section_title or "root"
            )

            chunk = IngestedChunk(
                chunk_id=chunk_id,
                content_markdown=section_content,
                embedding_text=embedding_text,
                evidence=evidence,
                source_hash=dm.source_hash,
                source_type=DocumentSource.S1000D_XML,
                word_count=word_count,
                effectivity_msns=dm.effectivity.msn_list,
                effectivity_fleet=(
                    dm.effectivity.fleet_types[0]
                    if dm.effectivity.fleet_types
                    else None
                ),
            )
            chunks.append(chunk)

        return chunks

    @staticmethod
    def _split_by_headers(markdown: str) -> List[Tuple[str, str]]:
        """Split markdown by ## headers into (title, content) pairs."""
        sections: List[Tuple[str, str]] = []
        current_title = ""
        current_lines: List[str] = []

        for line in markdown.split("\n"):
            if line.startswith("## "):
                if current_lines:
                    sections.append((current_title, "\n".join(current_lines)))
                current_title = line[3:].strip()
                current_lines = [line]
            elif line.startswith("# ") and not current_title:
                current_title = line[2:].strip()
                current_lines.append(line)
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_title, "\n".join(current_lines)))

        return sections

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove markdown syntax for clean embedding text."""
        import re
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
        text = re.sub(r"!\[.+?\]\(.+?\)", "", text)
        text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^-\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_s1000d_to_dom(file_path: str) -> List[RegulatoryNode]:
    """
    High-level function to extract DOM-compatible RegulatoryNodes from S1000D.
    Standardizes technical data for the Smart DMS knowledge graph.
    """
    parser = S1000DParser(file_path)
    result = parser.parse()
    
    nodes: List[RegulatoryNode] = []
    
    for dm in result.data_modules:
        node_id = dm.identification.dmc
        content = dm.content_markdown
        node_hash = generate_node_hash(node_id, content)
        
        # Root node for the Data Module
        root_node = RegulatoryNode(
            node_id=node_id,
            title=f"{dm.identification.tech_name} — {dm.identification.info_name or 'Procedure'}",
            content=content,
            content_hash=node_hash,
            node_type="DataModule",
            metadata={
                "model_ident": dm.identification.model_ident_code,
                "system_code": dm.identification.system_code,
                "info_code": dm.identification.info_code,
                "warnings_count": len(dm.warnings)
            }
        )
        nodes.append(root_node)
        
    return nodes
