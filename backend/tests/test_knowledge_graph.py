"""
Tests for the RegulatoryKnowledgeGraph module.
Covers graph construction, BFS traversal, conflict detection, and persistence.
"""

import os
import json
import pytest
from unittest.mock import patch
from knowledge_graph import RegulatoryKnowledgeGraph
from schemas import EasaRequirement, ManualChunk


class TestGraphConstruction:
    """Tests graph building from EASA requirements."""

    def test_build_from_rules(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        assert graph.is_built()
        assert graph.graph.number_of_nodes() > 0

    def test_agency_nodes_created(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        assert graph.graph.has_node("EASA")
        node_data = graph.graph.nodes["EASA"]
        assert node_data["node_type"] == "Agency"

    def test_rule_nodes_created(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        assert graph.graph.has_node("ADR.OR.B.005")
        assert graph.graph.has_node("ORO.FTL.210")

    def test_amc_node_type(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        # AMC requirement should be typed as AMC_GM
        amc_id = "AMC1 ADR.OR.B.005"
        if graph.graph.has_node(amc_id):
            assert graph.graph.nodes[amc_id]["node_type"] == "AMC_GM"

    def test_publishes_edges(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        # EASA should have PUBLISHES edges to rules
        edges = list(graph.graph.out_edges("EASA", data=True))
        assert len(edges) >= len(sample_regulatory_nodes)

    def test_cross_reference_edges(self):
        """Rules referencing other rules should create REFERENCES edges."""
        from ingestion.contracts import RegulatoryNode
        import hashlib
        
        c_hash1 = hashlib.sha256("In accordance with ORO.FTL.210, the operator shall...".encode()).hexdigest()
        c_hash2 = hashlib.sha256("Maximum FDP 13 hours.".encode()).hexdigest()
        
        rules = [
            RegulatoryNode(
                node_id="CAT.OP.MPA.150", node_type="Regulation",
                content="In accordance with ORO.FTL.210, the operator shall...", content_hash=c_hash1,
                title="Fuel Policy", metadata={"domain": "air-ops", "law_type": "Hard Law"}
            ),
            RegulatoryNode(
                node_id="ORO.FTL.210", node_type="Regulation",
                content="Maximum FDP 13 hours.", content_hash=c_hash2,
                title="FTL", metadata={"domain": "air-ops", "law_type": "Hard Law"}
            ),
        ]
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(rules)
        # CAT.OP.MPA.150 references ORO.FTL.210
        edges = list(graph.graph.out_edges("CAT.OP.MPA.150", data=True))
        ref_edges = [e for e in edges if e[2].get("edge_type") == "REFERENCES"]
        assert len(ref_edges) >= 1


class TestTraversal:
    """Tests BFS traversal and linked rule retrieval."""

    def test_traverse_returns_results(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        results = graph.traverse("ADR.OR.B.005", depth=2)
        assert len(results) >= 1
        assert results[0]["id"] == "ADR.OR.B.005"
        assert results[0]["hop"] == 0

    def test_traverse_nonexistent_node(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        results = graph.traverse("NONEXISTENT.999", depth=2)
        assert results == []

    def test_get_linked_rules(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        linked = graph.get_linked_rules("EASA", depth=1)
        assert isinstance(linked, list)

    def test_traverse_depth_limit(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        results_d0 = graph.traverse("ADR.OR.B.005", depth=0)
        results_d2 = graph.traverse("ADR.OR.B.005", depth=2)
        assert len(results_d0) <= len(results_d2)


class TestConflictDetection:
    """Tests graph-based conflict detection."""

    def test_no_conflicts_default(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        conflicts = graph.find_conflicts("ADR.OR.B.005")
        assert isinstance(conflicts, list)
        assert len(conflicts) == 0  # No CONFLICTS_WITH edges in sample data


class TestStats:
    """Tests graph statistics and health metrics."""

    def test_get_stats(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        stats = graph.get_stats()
        assert "total_nodes" in stats
        assert "total_edges" in stats
        assert stats["total_nodes"] > 0

    def test_get_graph_health(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        health = graph.get_graph_health()
        assert "orphan_nodes" in health
        assert "density" in health

    def test_get_neighbors_summary(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        neighbors = graph.get_neighbors_summary("ADR.OR.B.005")
        assert isinstance(neighbors, list)

    def test_get_neighbors_nonexistent(self, sample_regulatory_nodes):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        graph.build_from_rules(sample_regulatory_nodes)
        neighbors = graph.get_neighbors_summary("FAKE.ID.999")
        assert neighbors == []


class TestPersistence:
    """Tests graph save/load round-trip with encryption."""

    def test_persist_and_load(self, sample_regulatory_nodes, temp_dir):
        path = os.path.join(temp_dir, "graph.json.enc")
        graph = RegulatoryKnowledgeGraph(persist_path=path)
        graph.build_from_rules(sample_regulatory_nodes)
        graph.persist()

        # Load into a fresh graph
        graph2 = RegulatoryKnowledgeGraph(persist_path=path)
        success = graph2.load()
        assert success
        assert graph2.graph.number_of_nodes() == graph.graph.number_of_nodes()
        assert graph2.graph.number_of_edges() == graph.graph.number_of_edges()

    def test_load_nonexistent(self, temp_dir):
        path = os.path.join(temp_dir, "nonexistent.json.enc")
        graph = RegulatoryKnowledgeGraph(persist_path=path)
        assert not graph.load()

    def test_is_built_empty(self):
        graph = RegulatoryKnowledgeGraph(persist_path="nonexistent.json.enc")
        assert not graph.is_built()
