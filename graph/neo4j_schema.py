"""
Neo4j Graph Schema Definition — Schema-as-Code for the Aeronautical DMS.

Defines node labels, relationship types, property constraints, and indexes
as Python objects. Generates valid Cypher statements for Neo4j deployment.
Can be tested WITHOUT a running Neo4j instance.

Node Labels (7):
    Regulation, Procedure, Fleet, MSN, Manual, ManualSection, Agency

Relationship Types (8):
    MANDATES, APPLIES_TO, CONTRAVENES, REFERENCES, CLARIFIES,
    DOCUMENTS, PART_OF, PUBLISHED_BY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Node Labels
# ──────────────────────────────────────────────────────────────────────────────

class NodeLabel(str, Enum):
    """Neo4j node labels for the Aeronautical DMS graph."""
    REGULATION = "Regulation"
    PROCEDURE = "Procedure"
    FLEET = "Fleet"
    MSN = "MSN"
    MANUAL = "Manual"
    MANUAL_SECTION = "ManualSection"
    AGENCY = "Agency"


# ──────────────────────────────────────────────────────────────────────────────
# Relationship Types
# ──────────────────────────────────────────────────────────────────────────────

class RelationType(str, Enum):
    """Neo4j relationship types for the regulatory graph."""
    MANDATES = "MANDATES"          # Regulation → Procedure
    APPLIES_TO = "APPLIES_TO"      # Procedure → Fleet/MSN
    CONTRAVENES = "CONTRAVENES"    # Regulation ↔ Regulation
    REFERENCES = "REFERENCES"      # any → any
    CLARIFIES = "CLARIFIES"        # AMC/GM → Regulation
    DOCUMENTS = "DOCUMENTS"        # ManualSection → Procedure/Regulation
    PART_OF = "PART_OF"            # ManualSection → Manual, MSN → Fleet
    PUBLISHED_BY = "PUBLISHED_BY"  # Regulation → Agency


# ──────────────────────────────────────────────────────────────────────────────
# Property Definitions
# ──────────────────────────────────────────────────────────────────────────────

class PropertyType(str, Enum):
    """Supported Neo4j property types."""
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    LIST_STRING = "LIST<STRING>"


@dataclass
class PropertyDef:
    """Definition of a single node/relationship property."""
    name: str
    prop_type: PropertyType
    required: bool = False
    unique: bool = False
    indexed: bool = False
    description: str = ""


@dataclass
class NodeSchema:
    """Schema definition for a node label."""
    label: NodeLabel
    properties: List[PropertyDef] = field(default_factory=list)
    description: str = ""

    def get_unique_properties(self) -> List[PropertyDef]:
        return [p for p in self.properties if p.unique]

    def get_indexed_properties(self) -> List[PropertyDef]:
        return [p for p in self.properties if p.indexed]

    def get_required_properties(self) -> List[PropertyDef]:
        return [p for p in self.properties if p.required]


@dataclass
class RelationshipSchema:
    """Schema definition for a relationship type."""
    rel_type: RelationType
    from_label: NodeLabel
    to_label: NodeLabel
    properties: List[PropertyDef] = field(default_factory=list)
    description: str = ""
    bidirectional: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Schema Registry
# ──────────────────────────────────────────────────────────────────────────────

class AeronauticalDMSSchema:
    """
    Complete graph schema for the Aeronautical DMS.

    Usage:
        schema = AeronauticalDMSSchema()
        cypher_statements = schema.generate_cypher()
        for stmt in cypher_statements:
            neo4j_session.run(stmt)
    """

    def __init__(self):
        self.node_schemas: Dict[NodeLabel, NodeSchema] = {}
        self.relationship_schemas: List[RelationshipSchema] = []
        self._build_schema()

    def _build_schema(self):
        """Define the complete graph schema."""

        # ── Regulation ────────────────────────────────────────────────────
        self.node_schemas[NodeLabel.REGULATION] = NodeSchema(
            label=NodeLabel.REGULATION,
            description="EASA/FAA regulatory requirement or rule",
            properties=[
                PropertyDef("rule_id", PropertyType.STRING, required=True, unique=True, indexed=True,
                            description="Unique rule identifier (e.g., 'ADR.OR.B.005')"),
                PropertyDef("text", PropertyType.STRING, required=True,
                            description="Full text of the regulatory requirement"),
                PropertyDef("domain", PropertyType.STRING, indexed=True,
                            description="Regulatory domain (e.g., 'aerodromes', 'air-ops')"),
                PropertyDef("law_type", PropertyType.STRING, indexed=True,
                            description="Hard Law / Soft Law / Opinion / Guidance"),
                PropertyDef("source_title", PropertyType.STRING,
                            description="Title of the source document or topic"),
                PropertyDef("version", PropertyType.STRING,
                            description="Revision or version number"),
                PropertyDef("applicability_date", PropertyType.DATE,
                            description="Date the rule becomes applicable"),
                PropertyDef("agency", PropertyType.STRING, indexed=True,
                            description="Issuing agency (EASA, FAA, DGAC)"),
            ],
        )

        # ── Procedure ─────────────────────────────────────────────────────
        self.node_schemas[NodeLabel.PROCEDURE] = NodeSchema(
            label=NodeLabel.PROCEDURE,
            description="S1000D procedural data module",
            properties=[
                PropertyDef("dmc", PropertyType.STRING, required=True, unique=True, indexed=True,
                            description="S1000D Data Module Code"),
                PropertyDef("tech_name", PropertyType.STRING, required=True,
                            description="Technical name (e.g., 'Main landing gear')"),
                PropertyDef("info_name", PropertyType.STRING,
                            description="Information name (e.g., 'Removal')"),
                PropertyDef("system_code", PropertyType.STRING, indexed=True,
                            description="ATA system code (e.g., '32')"),
                PropertyDef("info_code", PropertyType.STRING, indexed=True,
                            description="S1000D info code (e.g., '520' for removal)"),
                PropertyDef("issue_number", PropertyType.STRING,
                            description="Current issue number"),
                PropertyDef("issue_date", PropertyType.DATE,
                            description="Issue date"),
                PropertyDef("content_hash", PropertyType.STRING,
                            description="SHA-256 hash of content for change detection"),
                PropertyDef("warning_count", PropertyType.INTEGER,
                            description="Number of warnings in the procedure"),
            ],
        )

        # ── Fleet ─────────────────────────────────────────────────────────
        self.node_schemas[NodeLabel.FLEET] = NodeSchema(
            label=NodeLabel.FLEET,
            description="Aircraft type / model (e.g., A320-214)",
            properties=[
                PropertyDef("type_code", PropertyType.STRING, required=True, unique=True, indexed=True,
                            description="Aircraft type code (e.g., 'A320-214')"),
                PropertyDef("manufacturer", PropertyType.STRING, required=True, indexed=True,
                            description="Manufacturer name"),
                PropertyDef("type_certificate", PropertyType.STRING,
                            description="EASA Type Certificate Data Sheet number"),
                PropertyDef("icao_designator", PropertyType.STRING,
                            description="ICAO type designator (e.g., 'A320')"),
            ],
        )

        # ── MSN ───────────────────────────────────────────────────────────
        self.node_schemas[NodeLabel.MSN] = NodeSchema(
            label=NodeLabel.MSN,
            description="Individual aircraft identified by MSN",
            properties=[
                PropertyDef("msn", PropertyType.STRING, required=True, unique=True, indexed=True,
                            description="Manufacturer Serial Number"),
                PropertyDef("registration", PropertyType.STRING, indexed=True,
                            description="Aircraft registration (e.g., 'F-GKXO')"),
                PropertyDef("operator", PropertyType.STRING, indexed=True,
                            description="Current operator / airline"),
                PropertyDef("delivery_date", PropertyType.DATE,
                            description="Date of delivery to operator"),
                PropertyDef("status", PropertyType.STRING,
                            description="Active / Storage / Retired"),
            ],
        )

        # ── Manual ────────────────────────────────────────────────────────
        self.node_schemas[NodeLabel.MANUAL] = NodeSchema(
            label=NodeLabel.MANUAL,
            description="Operator manual document (CAME, MOE, OM-A, etc.)",
            properties=[
                PropertyDef("manual_code", PropertyType.STRING, required=True, unique=True, indexed=True,
                            description="Manual identifier"),
                PropertyDef("manual_type", PropertyType.STRING, required=True, indexed=True,
                            description="CAME / MOE / OM-A / OM-B / AMM / MEL"),
                PropertyDef("revision", PropertyType.STRING,
                            description="Current revision number"),
                PropertyDef("revision_date", PropertyType.DATE,
                            description="Date of last revision"),
                PropertyDef("file_hash", PropertyType.STRING,
                            description="SHA-256 hash for version tracking"),
            ],
        )

        # ── ManualSection ─────────────────────────────────────────────────
        self.node_schemas[NodeLabel.MANUAL_SECTION] = NodeSchema(
            label=NodeLabel.MANUAL_SECTION,
            description="A section within an operator manual",
            properties=[
                PropertyDef("section_id", PropertyType.STRING, required=True, indexed=True,
                            description="Section identifier (e.g., '4.1.2')"),
                PropertyDef("title", PropertyType.STRING, required=True,
                            description="Section heading"),
                PropertyDef("page", PropertyType.INTEGER,
                            description="Page number in the manual"),
                PropertyDef("content_preview", PropertyType.STRING,
                            description="First 200 chars of content for display"),
                PropertyDef("has_diagram", PropertyType.BOOLEAN,
                            description="Whether this section has visual content"),
            ],
        )

        # ── Agency ────────────────────────────────────────────────────────
        self.node_schemas[NodeLabel.AGENCY] = NodeSchema(
            label=NodeLabel.AGENCY,
            description="Regulatory body (EASA, FAA, DGAC)",
            properties=[
                PropertyDef("code", PropertyType.STRING, required=True, unique=True, indexed=True,
                            description="Short code (e.g., 'EASA')"),
                PropertyDef("name", PropertyType.STRING, required=True,
                            description="Full name"),
                PropertyDef("jurisdiction", PropertyType.STRING,
                            description="Geographic jurisdiction (EU, US, FR)"),
            ],
        )

        # ── Relationships ─────────────────────────────────────────────────

        self.relationship_schemas = [
            RelationshipSchema(
                rel_type=RelationType.MANDATES,
                from_label=NodeLabel.REGULATION,
                to_label=NodeLabel.PROCEDURE,
                description="This regulation requires this procedure",
                properties=[
                    PropertyDef("mandate_type", PropertyType.STRING,
                                description="direct / indirect / conditional"),
                ],
            ),
            RelationshipSchema(
                rel_type=RelationType.APPLIES_TO,
                from_label=NodeLabel.PROCEDURE,
                to_label=NodeLabel.FLEET,
                description="This procedure applies to this aircraft type",
                properties=[
                    PropertyDef("effectivity_source", PropertyType.STRING,
                                description="Source of the applicability (DMC, SB, etc.)"),
                ],
            ),
            RelationshipSchema(
                rel_type=RelationType.CONTRAVENES,
                from_label=NodeLabel.REGULATION,
                to_label=NodeLabel.REGULATION,
                bidirectional=True,
                description="These regulations have conflicting requirements",
                properties=[
                    PropertyDef("conflict_type", PropertyType.STRING,
                                description="direct / interpretation / scope"),
                    PropertyDef("detected_at", PropertyType.DATE,
                                description="When the conflict was detected"),
                ],
            ),
            RelationshipSchema(
                rel_type=RelationType.REFERENCES,
                from_label=NodeLabel.REGULATION,
                to_label=NodeLabel.REGULATION,
                description="This regulation references another",
                properties=[
                    PropertyDef("reference_context", PropertyType.STRING,
                                description="Context of the reference"),
                ],
            ),
            RelationshipSchema(
                rel_type=RelationType.CLARIFIES,
                from_label=NodeLabel.REGULATION,
                to_label=NodeLabel.REGULATION,
                description="AMC/GM that clarifies a hard law",
            ),
            RelationshipSchema(
                rel_type=RelationType.DOCUMENTS,
                from_label=NodeLabel.MANUAL_SECTION,
                to_label=NodeLabel.REGULATION,
                description="Manual section that documents compliance with a regulation",
                properties=[
                    PropertyDef("compliance_level", PropertyType.STRING,
                                description="full / partial / gap"),
                ],
            ),
            RelationshipSchema(
                rel_type=RelationType.PART_OF,
                from_label=NodeLabel.MANUAL_SECTION,
                to_label=NodeLabel.MANUAL,
                description="Section belongs to this manual",
            ),
            RelationshipSchema(
                rel_type=RelationType.PUBLISHED_BY,
                from_label=NodeLabel.REGULATION,
                to_label=NodeLabel.AGENCY,
                description="Regulation issued by this agency",
            ),
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Cypher Generation
    # ──────────────────────────────────────────────────────────────────────────

    def generate_constraints(self) -> List[str]:
        """Generate Cypher CONSTRAINT statements for unique properties."""
        statements: List[str] = []
        for label, schema in self.node_schemas.items():
            for prop in schema.get_unique_properties():
                name = f"unique_{label.value.lower()}_{prop.name}"
                stmt = (
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (n:{label.value}) "
                    f"REQUIRE n.{prop.name} IS UNIQUE"
                )
                statements.append(stmt)
        return statements

    def generate_indexes(self) -> List[str]:
        """Generate Cypher INDEX statements for indexed (non-unique) properties."""
        statements: List[str] = []
        for label, schema in self.node_schemas.items():
            for prop in schema.get_indexed_properties():
                if prop.unique:
                    continue  # Unique constraints auto-create indexes
                name = f"idx_{label.value.lower()}_{prop.name}"
                stmt = (
                    f"CREATE INDEX {name} IF NOT EXISTS "
                    f"FOR (n:{label.value}) ON (n.{prop.name})"
                )
                statements.append(stmt)
        return statements

    def generate_cypher(self) -> List[str]:
        """Generate all Cypher schema statements (constraints + indexes)."""
        return self.generate_constraints() + self.generate_indexes()

    # ──────────────────────────────────────────────────────────────────────────
    # Introspection
    # ──────────────────────────────────────────────────────────────────────────

    def get_node_labels(self) -> List[str]:
        """Return all defined node labels."""
        return [label.value for label in self.node_schemas]

    def get_relationship_types(self) -> List[str]:
        """Return all defined relationship types."""
        return [r.rel_type.value for r in self.relationship_schemas]

    def get_schema_summary(self) -> Dict:
        """Return a summary of the schema for documentation/display."""
        return {
            "node_labels": len(self.node_schemas),
            "relationship_types": len(self.relationship_schemas),
            "total_properties": sum(
                len(s.properties) for s in self.node_schemas.values()
            ),
            "unique_constraints": sum(
                len(s.get_unique_properties()) for s in self.node_schemas.values()
            ),
            "indexes": sum(
                len(s.get_indexed_properties()) for s in self.node_schemas.values()
            ),
            "nodes": {
                label.value: {
                    "description": schema.description,
                    "properties": len(schema.properties),
                    "unique_keys": [p.name for p in schema.get_unique_properties()],
                }
                for label, schema in self.node_schemas.items()
            },
            "relationships": [
                {
                    "type": r.rel_type.value,
                    "from": r.from_label.value,
                    "to": r.to_label.value,
                    "description": r.description,
                    "bidirectional": r.bidirectional,
                }
                for r in self.relationship_schemas
            ],
        }

    def validate_relationship(
        self, rel_type: str, from_label: str, to_label: str
    ) -> bool:
        """Check if a relationship type is valid between two node labels."""
        for r in self.relationship_schemas:
            if r.rel_type.value == rel_type:
                if r.from_label.value == from_label and r.to_label.value == to_label:
                    return True
                if r.bidirectional and r.from_label.value == to_label and r.to_label.value == from_label:
                    return True
        return False
