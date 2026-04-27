"""
Regulatory Knowledge Graph — NetworkX-based multi-hop reasoning engine.
Supports EASA (and extensible to FAA/DGAC) with typed nodes and edges.
Persisted to JSON on disk.
"""

import json
import os
import re
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict, deque

import networkx as nx
import security

from schemas import EasaRequirement, ManualChunk, GraphNode, GraphEdge
from ingestion.contracts import RegulatoryNode
from graph.persistence import upsert_nodes_to_neo4j, upsert_edges_to_neo4j
from core_constants import EASA_RULE_ID_PATTERN, DOMAIN_TO_AGENCY


class RegulatoryKnowledgeGraph:
    """
    Directed graph of regulatory entities with multi-hop traversal.

    Node types: Agency, Regulation, AMC_GM, ManualSection, Diagram, TechnicalLimit
    Edge types: MANDATES, CLARIFIES, REFERENCES, CONFLICTS_WITH, CONTAINS_DIAGRAM
    """

    def __init__(self, persist_path: str = "data/graph/knowledge_graph.json.enc"):
        self.persist_path = persist_path
        self.graph = nx.DiGraph()
        self._rule_index: Dict[str, EasaRequirement] = {}
        # T1.1 - Initialisation de la Lookup Table pour la Résolution d'Entités
        self.entity_index: Dict[str, RegulatoryNode] = {}
    def _standardize_id(self, raw_id: str) -> str:
        """Nettoie l'ID pour garantir une résolution d'entité parfaite (T1.1)."""
        return raw_id.strip().upper()

    def build_index(self, validated_nodes: List[RegulatoryNode]):
        """Peuple l'index en mémoire avant toute interaction avec Neo4j (T1.1)."""
        import logging
        logger = logging.getLogger("regumap-ai.graph")
        logger.info(f"Début de l'indexation en mémoire : {len(validated_nodes)} entités...")
        
        for node in validated_nodes:
            clean_id = self._standardize_id(node.node_id)
            self.entity_index[clean_id] = node
            
        logger.info(f"Indexation terminée : {len(self.entity_index)} entités valides prêtes.")

    # ──────────────────────────────────────────────────────────────────────────
    # Build from data sources
    # ──────────────────────────────────────────────────────────────────────────

    def build_from_rules(self, rules: List[RegulatoryNode]):
        """
        Populates graph nodes and edges from validated regulatory entities.
        Uses in-memory index to ensure entity resolution (T1.1).
        Detects SUPERSEDES relationships via version comparison (Task 2).
        """
        import logging
        logger = logging.getLogger("regumap-ai.graph")
        
        # 1. PEUPLEMENT DE L'INDEX (T1.1 Étape 2.3)
        self.build_index(rules)

        logger.info(f"Construction du graphe à partir de {len(rules)} entités...")

        # Ensure Agency nodes exist
        for agency in set(DOMAIN_TO_AGENCY.values()):
            if not self.graph.has_node(agency):
                self.graph.add_node(agency, node_type="Agency", label=agency, domain=None)

        # Track base IDs → versions for SUPERSEDES detection
        base_id_versions: Dict[str, List[RegulatoryNode]] = {}

        for rule in rules:
            self._rule_index[rule.node_id] = rule
            domain = rule.metadata.get("domain", "unknown")
            agency = DOMAIN_TO_AGENCY.get(domain, "EASA")
            version = rule.metadata.get("version", "1")
            status = rule.metadata.get("status", "active")

            # Add rule node with version metadata
            self.graph.add_node(
                rule.node_id,
                node_type=rule.node_type,
                label=rule.title or rule.node_id,
                domain=domain,
                law_type=rule.metadata.get("law_type", "Unknown"),
                text_preview=rule.content[:200] if rule.content else "",
                version=version,
                status=status,
                content_hash=rule.content_hash,
            )

            # Edge: Agency → Regulation
            self.graph.add_edge(agency, rule.node_id, edge_type="PUBLISHES", weight=1.0)

            # Track versions by base ID (strip trailing version suffix)
            base_id = self._extract_base_id(rule.node_id)
            if base_id not in base_id_versions:
                base_id_versions[base_id] = []
            base_id_versions[base_id].append(rule)

            # 2. CRÉATION DES RELATIONS AVEC BARRIÈRE DE SÉCURITÉ O(1) (T1.1 Étape 2.4)
            ref_ids = set(EASA_RULE_ID_PATTERN.findall(rule.content)) - {rule.node_id}
            
            for ref_id in ref_ids:
                clean_ref_id = self._standardize_id(ref_id)
                target_node = self.entity_index.get(clean_ref_id)
                
                if target_node:
                    edge_type = self._infer_edge_type(rule, target_node)
                    self.graph.add_edge(
                        rule.node_id, target_node.node_id,
                        edge_type=edge_type,
                        weight=0.9,
                    )
                else:
                    logger.warning(f"Référence brisée détectée : {ref_id} cité dans {rule.node_id} est introuvable.")

        # 3. SUPERSEDES detection: link newer versions to older ones
        supersedes_count = 0
        for base_id, versions in base_id_versions.items():
            if len(versions) > 1:
                sorted_versions = sorted(
                    versions,
                    key=lambda r: r.metadata.get("version", "0"),
                )
                for i in range(1, len(sorted_versions)):
                    older = sorted_versions[i - 1]
                    newer = sorted_versions[i]
                    self.graph.add_edge(
                        newer.node_id, older.node_id,
                        edge_type="SUPERSEDES",
                        weight=1.0,
                    )
                    # Mark older as superseded
                    self.graph.nodes[older.node_id]["status"] = "superseded"
                    supersedes_count += 1

        logger.info(
            f"Graphe construit : {self.graph.number_of_nodes()} nœuds, "
            f"{self.graph.number_of_edges()} relations, "
            f"{supersedes_count} SUPERSEDES détectées."
        )

    @staticmethod
    def _extract_base_id(node_id: str) -> str:
        """Extracts base regulatory ID without version suffix.
        e.g., 'ORO.GEN.200.v2' → 'ORO.GEN.200'
        """
        # Strip trailing .vN or .issN suffix
        import re
        return re.sub(r'\.(v|iss)\d+$', '', node_id, flags=re.IGNORECASE)

    @staticmethod
    def _infer_edge_type(source: RegulatoryNode, target: RegulatoryNode) -> str:
        """Deterministic edge type inference based on node types."""
        src_type = source.node_type.upper()
        tgt_type = target.node_type.upper()

        # AMC/GM → IR/Regulation = CLARIFIES
        if ("AMC" in src_type or "GM" in src_type) and tgt_type in ("REGULATION", "IR", "CS"):
            return "CLARIFIES"
        # IR → Technical procedure = IMPLEMENTS
        if src_type in ("IR", "REGULATION") and tgt_type in ("DATAMODULE", "PROCEDURE"):
            return "IMPLEMENTS"
        # Default
        return "REFERENCES"

    def sync_to_neo4j(self, driver):
        """
        Synchronise le graphe NetworkX vers Neo4j de manière idempotente (T1.2).
        Utilise le batching pour optimiser les performances.
        """
        import logging
        logger = logging.getLogger("regumap-ai.graph-sync")
        logger.info("Synchronisation du Gumeau Numérique vers Neo4j...")

        # 1. Upsert des Nœuds
        nodes_batch = list(self.entity_index.values())
        upsert_nodes_to_neo4j(driver, nodes_batch)

        # 2. Upsert des Relations (Edges)
        edges_batch = []
        for source, target, data in self.graph.edges(data=True):
            # On ignore les relations vers les Agences pour ce batch (déjà géré ou à part)
            if source in self.entity_index and target in self.entity_index:
                edges_batch.append({
                    "source_id": source,
                    "target_id": target,
                    "weight": data.get("weight", 1.0),
                    "type": data.get("edge_type", "LINKED_TO")
                })
        
        upsert_edges_to_neo4j(driver, edges_batch)
        logger.info("Synchronisation Neo4j terminée avec succès. ✅")

    def build_from_manual(self, chunks: List[ManualChunk], rule_chunk_map: Dict[str, List[ManualChunk]]):
        """
        Adds ManualSection nodes and links them to matched regulations.
        """
        for chunk in chunks:
            chunk_id = f"MANUAL:p{chunk.page_number}:{chunk.section_title[:40]}"

            self.graph.add_node(
                chunk_id,
                node_type="ManualSection",
                label=chunk.section_title,
                domain=None,
                page=chunk.page_number,
                has_diagram=chunk.has_diagram,
            )

            # Link diagram nodes
            if chunk.has_diagram and chunk.diagram_path:
                diag_id = f"DIAGRAM:{chunk.diagram_path}"
                self.graph.add_node(
                    diag_id,
                    node_type="Diagram",
                    label=f"Diagram on page {chunk.page_number}",
                    domain=None,
                    path=chunk.diagram_path,
                )
                self.graph.add_edge(chunk_id, diag_id, edge_type="CONTAINS_DIAGRAM", weight=1.0)

        # Link regulations → manual sections via the pre-filtered mapping
        for rule_id, mapped_chunks in rule_chunk_map.items():
            for chunk in mapped_chunks:
                chunk_id = f"MANUAL:p{chunk.page_number}:{chunk.section_title[:40]}"
                if self.graph.has_node(chunk_id):
                    self.graph.add_edge(
                        rule_id, chunk_id,
                        edge_type="MANDATES",
                        weight=0.8,
                    )

    # ──────────────────────────────────────────────────────────────────────────
    # Multi-hop traversal
    # ──────────────────────────────────────────────────────────────────────────

    def traverse(self, start_id: str, depth: int = 2, edge_types: Optional[Set[str]] = None) -> List[Dict]:
        """
        BFS traversal from a starting node up to `depth` hops.
        Returns list of dicts with node info and hop distance.
        """
        if not self.graph.has_node(start_id):
            return []

        visited: Set[str] = set()
        queue: deque = deque([(start_id, 0)])
        results: List[Dict] = []

        while queue:
            node_id, d = queue.popleft()
            if node_id in visited or d > depth:
                continue
            visited.add(node_id)

            node_data = self.graph.nodes[node_id]
            results.append({
                "id": node_id,
                "hop": d,
                **node_data,
            })

            # Traverse outgoing edges
            for _, neighbor, edge_data in self.graph.out_edges(node_id, data=True):
                if edge_types and edge_data.get("edge_type") not in edge_types:
                    continue
                if neighbor not in visited:
                    queue.append((neighbor, d + 1))

            # Also traverse incoming edges (for CLARIFIES relationships)
            for predecessor, _, edge_data in self.graph.in_edges(node_id, data=True):
                if edge_types and edge_data.get("edge_type") not in edge_types:
                    continue
                if predecessor not in visited:
                    queue.append((predecessor, d + 1))

        return results

    def get_linked_rules(self, rule_id: str, depth: int = 2) -> List[EasaRequirement]:
        """
        Returns EasaRequirement objects for all regulation/AMC_GM nodes
        reachable within `depth` hops from the given rule.
        """
        traversed = self.traverse(rule_id, depth=depth)
        linked = []
        for node in traversed:
            if node["id"] == rule_id:
                continue
            if node.get("node_type") in ("Regulation", "AMC_GM"):
                req = self._rule_index.get(node["id"])
                if req:
                    linked.append(req)
        return linked

    def find_conflicts(self, rule_id: str) -> List[Dict]:
        """
        Returns all CONFLICTS_WITH edges connected to the given rule.
        Extensible: when FAA rules are added, cross-agency conflicts show here.
        """
        conflicts = []
        for _, target, data in self.graph.out_edges(rule_id, data=True):
            if data.get("edge_type") == "CONFLICTS_WITH":
                conflicts.append({"source": rule_id, "target": target, **data})
        for source, _, data in self.graph.in_edges(rule_id, data=True):
            if data.get("edge_type") == "CONFLICTS_WITH":
                conflicts.append({"source": source, "target": rule_id, **data})
        return conflicts

    # ──────────────────────────────────────────────────────────────────────────
    # Stats & inspection
    # ──────────────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Returns node/edge counts grouped by type."""
        node_counts = defaultdict(int)
        edge_counts = defaultdict(int)

        for _, data in self.graph.nodes(data=True):
            node_counts[data.get("node_type", "Unknown")] += 1
        for _, _, data in self.graph.edges(data=True):
            edge_counts[data.get("edge_type", "Unknown")] += 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "nodes_by_type": dict(node_counts),
            "edges_by_type": dict(edge_counts),
        }

    def get_neighbors_summary(self, rule_id: str) -> List[Dict]:
        """Returns immediate neighbors with edge info for display."""
        if not self.graph.has_node(rule_id):
            return []

        neighbors = []
        for _, target, data in self.graph.out_edges(rule_id, data=True):
            target_data = self.graph.nodes.get(target, {})
            neighbors.append({
                "id": target,
                "edge_type": data.get("edge_type", "UNKNOWN"),
                "node_type": target_data.get("node_type", "Unknown"),
                "label": target_data.get("label", target),
                "direction": "outgoing",
            })
        for source, _, data in self.graph.in_edges(rule_id, data=True):
            source_data = self.graph.nodes.get(source, {})
            neighbors.append({
                "id": source,
                "edge_type": data.get("edge_type", "UNKNOWN"),
                "node_type": source_data.get("node_type", "Unknown"),
                "label": source_data.get("label", source),
                "direction": "incoming",
            })
        return neighbors

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def persist(self):
        """Save graph to encrypted JSON file."""
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        data = nx.node_link_data(self.graph, edges="links")
        security.secure_save_json(self.persist_path, data)
        print(f"Knowledge graph saved securely to {self.persist_path}")

    def load(self) -> bool:
        """Load graph from encrypted JSON file. Returns True if successful."""
        data = security.secure_load_json(self.persist_path)
        if data:
            self.graph = nx.node_link_graph(data, directed=True, edges="links")
            print(f"Knowledge graph loaded securely: {self.graph.number_of_nodes()} nodes.")
            return True
        return False

    def is_built(self) -> bool:
        return self.graph.number_of_nodes() > 0

    def find_orphan_nodes(self) -> List[str]:
        """Returns node IDs with zero edges (orphans = weak graph connectivity)."""
        return [
            n for n in self.graph.nodes()
            if self.graph.degree(n) == 0
        ]

    def get_graph_health(self) -> Dict:
        """Returns health metrics for the graph: orphans, connectivity, density."""
        orphans = self.find_orphan_nodes()
        n_nodes = self.graph.number_of_nodes()
        n_edges = self.graph.number_of_edges()
        density = nx.density(self.graph) if n_nodes > 1 else 0.0
        # Weakly connected components (treat as undirected)
        n_components = nx.number_weakly_connected_components(self.graph) if n_nodes > 0 else 0
        return {
            "total_nodes": n_nodes,
            "total_edges": n_edges,
            "orphan_nodes": len(orphans),
            "orphan_pct": f"{len(orphans) / max(n_nodes, 1) * 100:.1f}%",
            "density": f"{density:.6f}",
            "weakly_connected_components": n_components,
            "avg_degree": f"{sum(d for _, d in self.graph.degree()) / max(n_nodes, 1):.2f}",
        }
