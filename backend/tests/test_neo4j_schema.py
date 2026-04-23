"""
Tests for the Neo4j graph schema definition.
Validates: node labels, relationship types, Cypher generation, and schema introspection.
"""

import pytest
from graph.neo4j_schema import (
    AeronauticalDMSSchema,
    NodeLabel,
    RelationType,
    PropertyType,
)


@pytest.fixture
def schema():
    return AeronauticalDMSSchema()


class TestNodeLabels:
    """Validates all 7 node labels are defined."""

    def test_all_labels_present(self, schema):
        labels = schema.get_node_labels()
        assert "Regulation" in labels
        assert "Procedure" in labels
        assert "Fleet" in labels
        assert "MSN" in labels
        assert "Manual" in labels
        assert "ManualSection" in labels
        assert "Agency" in labels

    def test_label_count(self, schema):
        assert len(schema.get_node_labels()) == 7

    def test_regulation_has_rule_id(self, schema):
        reg = schema.node_schemas[NodeLabel.REGULATION]
        prop_names = [p.name for p in reg.properties]
        assert "rule_id" in prop_names

    def test_regulation_rule_id_is_unique(self, schema):
        reg = schema.node_schemas[NodeLabel.REGULATION]
        unique_keys = [p.name for p in reg.get_unique_properties()]
        assert "rule_id" in unique_keys

    def test_procedure_has_dmc(self, schema):
        proc = schema.node_schemas[NodeLabel.PROCEDURE]
        prop_names = [p.name for p in proc.properties]
        assert "dmc" in prop_names

    def test_procedure_dmc_is_unique(self, schema):
        proc = schema.node_schemas[NodeLabel.PROCEDURE]
        unique_keys = [p.name for p in proc.get_unique_properties()]
        assert "dmc" in unique_keys

    def test_msn_has_msn_field(self, schema):
        msn = schema.node_schemas[NodeLabel.MSN]
        prop_names = [p.name for p in msn.properties]
        assert "msn" in prop_names
        assert "registration" in prop_names
        assert "operator" in prop_names

    def test_fleet_has_type_code(self, schema):
        fleet = schema.node_schemas[NodeLabel.FLEET]
        prop_names = [p.name for p in fleet.properties]
        assert "type_code" in prop_names
        assert "manufacturer" in prop_names

    def test_manual_has_manual_type(self, schema):
        manual = schema.node_schemas[NodeLabel.MANUAL]
        prop_names = [p.name for p in manual.properties]
        assert "manual_type" in prop_names
        assert "revision" in prop_names

    def test_agency_has_code(self, schema):
        agency = schema.node_schemas[NodeLabel.AGENCY]
        prop_names = [p.name for p in agency.properties]
        assert "code" in prop_names


class TestRelationshipTypes:
    """Validates all 8 relationship types."""

    def test_all_types_present(self, schema):
        types = schema.get_relationship_types()
        assert "MANDATES" in types
        assert "APPLIES_TO" in types
        assert "CONTRAVENES" in types
        assert "REFERENCES" in types
        assert "CLARIFIES" in types
        assert "DOCUMENTS" in types
        assert "PART_OF" in types
        assert "PUBLISHED_BY" in types

    def test_relationship_count(self, schema):
        assert len(schema.get_relationship_types()) == 8

    def test_mandates_direction(self, schema):
        """MANDATES: Regulation → Procedure."""
        assert schema.validate_relationship("MANDATES", "Regulation", "Procedure")
        assert not schema.validate_relationship("MANDATES", "Procedure", "Regulation")

    def test_applies_to_direction(self, schema):
        """APPLIES_TO: Procedure → Fleet."""
        assert schema.validate_relationship("APPLIES_TO", "Procedure", "Fleet")

    def test_contravenes_bidirectional(self, schema):
        """CONTRAVENES: Regulation ↔ Regulation (bidirectional)."""
        assert schema.validate_relationship("CONTRAVENES", "Regulation", "Regulation")

    def test_documents_direction(self, schema):
        """DOCUMENTS: ManualSection → Regulation."""
        assert schema.validate_relationship("DOCUMENTS", "ManualSection", "Regulation")

    def test_part_of_direction(self, schema):
        """PART_OF: ManualSection → Manual."""
        assert schema.validate_relationship("PART_OF", "ManualSection", "Manual")

    def test_invalid_relationship(self, schema):
        """Invalid relationship should return False."""
        assert not schema.validate_relationship("MANDATES", "MSN", "Agency")
        assert not schema.validate_relationship("NONEXISTENT", "Regulation", "Procedure")


class TestCypherGeneration:
    """Validates Cypher statement generation."""

    def test_constraints_generated(self, schema):
        constraints = schema.generate_constraints()
        assert len(constraints) > 0
        for stmt in constraints:
            assert "CREATE CONSTRAINT" in stmt
            assert "IF NOT EXISTS" in stmt
            assert "IS UNIQUE" in stmt

    def test_indexes_generated(self, schema):
        indexes = schema.generate_indexes()
        assert len(indexes) > 0
        for stmt in indexes:
            assert "CREATE INDEX" in stmt
            assert "IF NOT EXISTS" in stmt

    def test_all_cypher_valid_syntax(self, schema):
        all_stmts = schema.generate_cypher()
        assert len(all_stmts) > 0
        for stmt in all_stmts:
            assert isinstance(stmt, str)
            assert len(stmt) > 10
            # Every statement should reference a node label
            assert any(label in stmt for label in schema.get_node_labels())

    def test_regulation_constraint_exists(self, schema):
        constraints = schema.generate_constraints()
        reg_constraints = [c for c in constraints if "Regulation" in c]
        assert len(reg_constraints) >= 1
        assert any("rule_id" in c for c in reg_constraints)

    def test_procedure_constraint_exists(self, schema):
        constraints = schema.generate_constraints()
        proc_constraints = [c for c in constraints if "Procedure" in c]
        assert len(proc_constraints) >= 1
        assert any("dmc" in c for c in proc_constraints)


class TestSchemaIntrospection:
    """Tests schema summary and metadata."""

    def test_summary_structure(self, schema):
        summary = schema.get_schema_summary()
        assert summary["node_labels"] == 7
        assert summary["relationship_types"] == 8
        assert summary["total_properties"] > 20
        assert summary["unique_constraints"] >= 6  # 6 of 7 labels have unique keys (ManualSection uses composite)

    def test_summary_nodes_detail(self, schema):
        summary = schema.get_schema_summary()
        nodes = summary["nodes"]
        assert "Regulation" in nodes
        assert "description" in nodes["Regulation"]
        assert "rule_id" in nodes["Regulation"]["unique_keys"]

    def test_summary_relationships_detail(self, schema):
        summary = schema.get_schema_summary()
        rels = summary["relationships"]
        mandates = [r for r in rels if r["type"] == "MANDATES"][0]
        assert mandates["from"] == "Regulation"
        assert mandates["to"] == "Procedure"
        assert mandates["bidirectional"] is False

        contravenes = [r for r in rels if r["type"] == "CONTRAVENES"][0]
        assert contravenes["bidirectional"] is True
