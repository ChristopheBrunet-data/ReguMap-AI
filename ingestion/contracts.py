"""
Ingestion Contracts — Canonical Pydantic data contracts for the ReguMap-AI ingestion pipeline.

Every parser (PDF, EASA XML, S1000D XML) MUST produce output conforming to these contracts.
The contracts enforce the "Evidence-First" requirement: every chunk carries a precise
document coordinate (page, paragraph, DMC, MSN) so the RAG engine never generates
citations without traceability.

Standards reference:
    - S1000D Issue 5.0 (Data Module structure, DMC, effectivity)
    - EASA Easy Access Rules (ERulesId, domain classification)
    - iSpec 2200 / ATA chapters (aircraft system codes)
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class DocumentSource(str, Enum):
    """Origin format of the ingested document."""
    PDF = "PDF"
    EASA_XML = "EASA_XML"
    S1000D_XML = "S1000D_XML"
    MANUAL = "MANUAL"


class ManualType(str, Enum):
    """EASA-standard manual classifications."""
    OM_A = "OM-A"           # Operations Manual Part A (General)
    OM_B = "OM-B"           # Operations Manual Part B (Aircraft Type)
    OM_C = "OM-C"           # Operations Manual Part C (Routes & Aerodromes)
    OM_D = "OM-D"           # Operations Manual Part D (Training)
    CAME = "CAME"           # Continuing Airworthiness Management Exposition
    MOE = "MOE"             # Maintenance Organisation Exposition
    MEL = "MEL"             # Minimum Equipment List
    STC = "STC"             # Supplemental Type Certificate
    AMM = "AMM"             # Aircraft Maintenance Manual
    IPC = "IPC"             # Illustrated Parts Catalogue
    OTHER = "OTHER"


class LawType(str, Enum):
    """Classification of regulatory text binding strength."""
    HARD_LAW = "Hard Law"       # Implementing Rules — legally binding
    SOFT_LAW = "Soft Law"       # AMC/GM — acceptable means of compliance
    OPINION = "Opinion"         # NPA / Opinion — proposed amendments
    GUIDANCE = "Guidance"       # Informational / guidance material


class S1000DInfoCode(str, Enum):
    """Common S1000D information codes for data module classification."""
    DESCRIPTION = "040"         # Description / Operation
    PROCEDURE = "520"           # Remove procedure
    PROCEDURE_INSTALL = "720"   # Install procedure
    FAULT_ISOLATION = "300"     # Fault isolation / troubleshooting
    ILLUSTRATED_PARTS = "941"   # Illustrated parts data
    WIRING = "400"              # Wiring data


# ──────────────────────────────────────────────────────────────────────────────
# Evidence Coordinates (The "Evidence-First" Core)
# ──────────────────────────────────────────────────────────────────────────────

class EvidenceCoordinate(BaseModel):
    """
    Precise document location for RAG traceability.

    Every ingested chunk MUST carry at least one coordinate so the system
    can cite the exact source of any compliance finding. This is the
    "Evidence-First" contract — no free-text generation without coordinates.
    """
    source_type: DocumentSource = Field(
        ..., description="Format of the source document"
    )
    document_id: str = Field(
        ..., description="Unique document identifier (file hash, DMC, or ERulesId)"
    )

    # PDF-specific coordinates
    page: Optional[int] = Field(
        None, description="1-indexed page number in the source PDF"
    )
    bbox: Optional[Tuple[float, float, float, float]] = Field(
        None, description="Bounding box (x0, y0, x1, y1) on the page"
    )

    # S1000D-specific coordinates
    dmc: Optional[str] = Field(
        None, description="S1000D Data Module Code (e.g., 'M1-32-00-00-00AA-520A-A')"
    )
    step_path: Optional[str] = Field(
        None, description="XPath-like path to the procedural step (e.g., 'mainProcedure/step[3]/step[1]')"
    )

    # EASA-specific coordinates
    erules_id: Optional[str] = Field(
        None, description="EASA ERules identifier (e.g., 'ADR.OR.B.005')"
    )

    # Universal coordinates
    paragraph_id: Optional[str] = Field(
        None, description="Section or paragraph identifier (e.g., '4.1.2')"
    )
    section_title: Optional[str] = Field(
        None, description="Human-readable section heading"
    )

    def citation_string(self) -> str:
        """Returns a human-readable citation string for UI display."""
        parts = []
        if self.dmc:
            parts.append(f"DMC {self.dmc}")
        if self.erules_id:
            parts.append(f"Rule {self.erules_id}")
        if self.page:
            parts.append(f"Page {self.page}")
        if self.paragraph_id:
            parts.append(f"§{self.paragraph_id}")
        if self.section_title:
            parts.append(f'"{self.section_title}"')
        if self.step_path:
            parts.append(f"Step {self.step_path}")
        return ", ".join(parts) if parts else f"[{self.source_type.value}] {self.document_id}"


# ──────────────────────────────────────────────────────────────────────────────
# Ingested Chunk (Universal output of all parsers)
# ──────────────────────────────────────────────────────────────────────────────

class IngestedChunk(BaseModel):
    """
    Universal chunk produced by any parser. This is the canonical unit
    that flows into the vector store and knowledge graph.
    """
    chunk_id: str = Field(
        ..., description="Deterministic ID: hash(document_id + coordinate)"
    )
    content_markdown: str = Field(
        ..., description="Clean Markdown content for display and LLM context"
    )
    embedding_text: str = Field(
        ..., description="Optimized plain text for vector embedding (no markdown syntax)"
    )
    evidence: EvidenceCoordinate = Field(
        ..., description="Precise source coordinate — the 'evidence-first' anchor"
    )
    source_hash: str = Field(
        ..., description="SHA-256 hash of the source file for version tracking"
    )

    # Metadata
    source_type: DocumentSource = Field(
        ..., description="Origin format"
    )
    word_count: int = Field(
        0, description="Word count of the embedding text"
    )
    has_visual: bool = Field(
        False, description="Whether this chunk contains diagrams, tables, or figures"
    )
    visual_path: Optional[str] = Field(
        None, description="Path to extracted visual evidence image"
    )

    # S1000D-specific
    effectivity_msns: List[str] = Field(
        default_factory=list,
        description="MSN numbers this chunk applies to (empty = all aircraft)"
    )
    effectivity_fleet: Optional[str] = Field(
        None, description="Fleet/aircraft type this chunk applies to"
    )

    @staticmethod
    def generate_chunk_id(document_id: str, coordinate_str: str) -> str:
        """Generates a deterministic chunk ID from document + coordinate."""
        raw = f"{document_id}::{coordinate_str}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────────
# S1000D Data Module Contracts
# ──────────────────────────────────────────────────────────────────────────────

class S1000DIdentification(BaseModel):
    """
    Identification data extracted from <identAndStatusSection>.
    Maps to the S1000D Data Module Code (DMC) structure.
    """
    dmc: str = Field(
        ..., description="Full Data Module Code string"
    )
    model_ident_code: str = Field(
        ..., description="Model identification code (e.g., 'A320', 'B737')"
    )
    system_code: str = Field(
        ..., description="ATA system code (e.g., '32' for landing gear)"
    )
    sub_system_code: Optional[str] = Field(
        None, description="Sub-system code"
    )
    assy_code: Optional[str] = Field(
        None, description="Assembly code"
    )
    info_code: str = Field(
        ..., description="Information code (e.g., '520' for removal procedure)"
    )
    tech_name: str = Field(
        ..., description="Technical name (e.g., 'Main landing gear')"
    )
    info_name: Optional[str] = Field(
        None, description="Information name (e.g., 'Removal')"
    )
    issue_number: str = Field(
        "001", description="Issue number"
    )
    in_work: str = Field(
        "00", description="In-work version"
    )
    issue_date: Optional[date] = Field(
        None, description="Issue date"
    )
    language: str = Field(
        "en", description="ISO 639-1 language code"
    )
    country: str = Field(
        "US", description="ISO 3166-1 country code"
    )


class S1000DEffectivity(BaseModel):
    """
    Effectivity / Applicability block from an S1000D Data Module.
    Defines which aircraft (by MSN, fleet type, or serial range) a procedure applies to.
    """
    msn_list: List[str] = Field(
        default_factory=list,
        description="Specific MSN numbers this module applies to (empty = all)"
    )
    fleet_types: List[str] = Field(
        default_factory=list,
        description="Aircraft type codes (e.g., ['A320-214', 'A320-232'])"
    )
    serial_range_start: Optional[str] = Field(
        None, description="Start of serial number range"
    )
    serial_range_end: Optional[str] = Field(
        None, description="End of serial number range"
    )
    applies_to_all: bool = Field(
        False, description="True if module applies to all aircraft in the fleet"
    )

    def matches_msn(self, msn: str) -> bool:
        """Check if a given MSN is within this effectivity scope."""
        if self.applies_to_all:
            return True
        if msn in self.msn_list:
            return True
        if self.serial_range_start and self.serial_range_end:
            return self.serial_range_start <= msn <= self.serial_range_end
        return len(self.msn_list) == 0 and len(self.fleet_types) == 0


class S1000DDataModule(BaseModel):
    """
    Complete representation of a parsed S1000D Data Module.
    This is the output of the S1000D parser before chunking.
    """
    identification: S1000DIdentification = Field(
        ..., description="Module identification and metadata"
    )
    effectivity: S1000DEffectivity = Field(
        default_factory=S1000DEffectivity,
        description="Applicability / effectivity scope"
    )
    content_markdown: str = Field(
        ..., description="Full content converted to clean Markdown"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Extracted warnings"
    )
    cautions: List[str] = Field(
        default_factory=list, description="Extracted cautions"
    )
    notes: List[str] = Field(
        default_factory=list, description="Extracted notes"
    )
    dm_references: List[str] = Field(
        default_factory=list, description="DMC references to other data modules"
    )
    figure_references: List[str] = Field(
        default_factory=list, description="Figure/illustration references"
    )
    source_hash: str = Field(
        ..., description="SHA-256 hash of the source XML file"
    )
    raw_xml_path: Optional[str] = Field(
        None, description="Path to the source XML file"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fleet / MSN Configuration
# ──────────────────────────────────────────────────────────────────────────────

class FleetConfig(BaseModel):
    """
    Maps MSN numbers to aircraft types for effectivity filtering.
    This is the operator's fleet configuration used by the Smart DMS.
    """
    fleet_type: str = Field(
        ..., description="Aircraft type code (e.g., 'A320-214')"
    )
    manufacturer: str = Field(
        ..., description="Manufacturer (e.g., 'Airbus', 'Boeing')"
    )
    type_certificate: Optional[str] = Field(
        None, description="EASA Type Certificate number"
    )
    msn_list: List[str] = Field(
        default_factory=list,
        description="List of MSN numbers for this fleet type"
    )
    registration_map: Dict[str, str] = Field(
        default_factory=dict,
        description="MSN → Registration mapping (e.g., {'1234': 'F-GKXO'})"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion Pipeline Result
# ──────────────────────────────────────────────────────────────────────────────

class IngestionResult(BaseModel):
    """
    Batch result returned by any parser's `ingest()` method.
    Contains the produced chunks plus operational metadata.
    """
    source_path: str = Field(..., description="Path to the source file")
    source_type: DocumentSource = Field(..., description="Source format")
    source_hash: str = Field(..., description="SHA-256 hash of the source file")
    chunks: List[IngestedChunk] = Field(
        default_factory=list, description="Produced chunks"
    )
    data_modules: List[S1000DDataModule] = Field(
        default_factory=list, description="Parsed S1000D data modules (if applicable)"
    )
    total_chunks: int = Field(0, description="Total number of chunks produced")
    errors: List[str] = Field(
        default_factory=list, description="Non-fatal errors encountered during parsing"
    )
    warnings_extracted: int = Field(0, description="Total warnings found")
    duration_seconds: float = Field(0.0, description="Parsing duration")

    def is_success(self) -> bool:
        """Returns True if at least one chunk was produced."""
        return self.total_chunks > 0
