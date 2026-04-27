"""
Unified Ingestion Service — Orchestrates the full fetch→parse→graph→index pipeline.

Chains: crawler → parser → knowledge_graph → neo4j_sync → vector_index
Emits events via EventBus on completion for downstream pillars.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.event_bus import Event, EventType, get_event_bus
from ingestion.contracts import RegulatoryNode

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Graph Diff (Task 9)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GraphDelta:
    """Result of comparing new ingestion against existing graph state."""
    added: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.removed)

    def summary(self) -> str:
        return (
            f"+{len(self.added)} added, ~{len(self.modified)} modified, "
            f"-{len(self.removed)} removed, ={self.unchanged} unchanged"
        )


def compute_graph_delta(
    existing_hashes: Dict[str, str],
    new_nodes: List[RegulatoryNode],
) -> GraphDelta:
    """
    Compares new ingestion results against existing node hashes.
    Returns a GraphDelta describing what changed.
    """
    delta = GraphDelta()
    new_ids = set()

    for node in new_nodes:
        new_ids.add(node.node_id)
        old_hash = existing_hashes.get(node.node_id)

        if old_hash is None:
            delta.added.append(node.node_id)
        elif old_hash != node.content_hash:
            delta.modified.append(node.node_id)
        else:
            delta.unchanged += 1

    # Nodes in existing but not in new = removed (only if we're doing a full re-sync)
    for existing_id in existing_hashes:
        if existing_id not in new_ids:
            delta.removed.append(existing_id)

    return delta


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion Service (Task 3)
# ──────────────────────────────────────────────────────────────────────────────

class IngestionService:
    """
    Orchestrates the end-to-end ingestion pipeline.

    Usage:
        service = IngestionService(engine, neo4j_driver)
        result = await service.run_full_pipeline()
        result = await service.run_single_domain("aerodromes")
    """

    def __init__(self, engine: Any, neo4j_driver: Any = None):
        self.engine = engine
        self.neo4j_driver = neo4j_driver
        self.bus = get_event_bus()
        self._last_hashes: Dict[str, str] = {}

    async def run_full_pipeline(self, force_crawl: bool = False) -> Dict[str, Any]:
        """
        Full pipeline: crawl all EASA domains → parse → build graph → sync Neo4j → build index.
        Returns summary of what happened.
        """
        start = time.time()
        results: Dict[str, Any] = {"domains": {}, "errors": []}

        # 1. CRAWL
        logger.info("Step 1/4: Crawling EASA domains...")
        try:
            from crawler import sync_all_domains
            xml_paths = sync_all_domains(force=force_crawl)
            results["crawled_domains"] = len(xml_paths)
        except Exception as e:
            logger.error(f"Crawl failed: {e}")
            results["errors"].append(f"Crawl: {e}")
            xml_paths = {}

        if not xml_paths:
            from crawler import get_all_xml_paths
            xml_paths = get_all_xml_paths()

        # 2. PARSE
        logger.info(f"Step 2/4: Parsing {len(xml_paths)} XML files...")
        all_nodes: List[RegulatoryNode] = []

        for domain, xml_path in xml_paths.items():
            try:
                nodes = self._parse_domain(domain, xml_path)
                all_nodes.extend(nodes)
                results["domains"][domain] = {"nodes": len(nodes), "status": "ok"}
            except Exception as e:
                logger.error(f"Parse failed for {domain}: {e}")
                results["domains"][domain] = {"nodes": 0, "status": f"error: {e}"}
                results["errors"].append(f"Parse {domain}: {e}")

        if not all_nodes:
            results["status"] = "no_data"
            return results

        # 3. GRAPH DIFF (Task 9)
        logger.info("Step 3/4: Computing graph diff and building knowledge graph...")
        delta = compute_graph_delta(self._last_hashes, all_nodes)
        logger.info(f"Graph delta: {delta.summary()}")
        results["delta"] = delta.summary()

        # Update hash cache
        self._last_hashes = {n.node_id: n.content_hash for n in all_nodes}

        # Build knowledge graph
        self.engine.knowledge_graph.build_from_rules(all_nodes)

        # Sync to Neo4j if available
        if self.neo4j_driver:
            try:
                self.engine.knowledge_graph.sync_to_neo4j(self.neo4j_driver)
            except Exception as e:
                logger.error(f"Neo4j sync failed: {e}")
                results["errors"].append(f"Neo4j: {e}")

        # 4. BUILD VECTOR INDEX
        logger.info("Step 4/4: Building vector index...")
        from schemas import EasaRequirement
        easa_rules = [
            EasaRequirement(
                id=node.node_id,
                text=node.content,
                type=node.node_type,
                source_title=node.title or node.node_id,
                domain=node.metadata.get("domain"),
                amc_gm_info="Hard Law" if node.node_type in ("Regulation", "IR") else "Soft Law",
            )
            for node in all_nodes
        ]
        self.engine.build_rule_index(easa_rules)

        duration = round(time.time() - start, 2)
        results["total_nodes"] = len(all_nodes)
        results["duration_seconds"] = duration
        results["status"] = "complete"

        # EMIT EVENTS
        await self.bus.publish(Event(
            event_type=EventType.RULES_UPDATED,
            source="ingestion_service",
            data={"count": len(all_nodes), "domains": list(xml_paths.keys())},
        ))

        if delta.has_changes:
            await self.bus.publish(Event(
                event_type=EventType.GRAPH_CHANGED,
                source="ingestion_service",
                data={
                    "added": delta.added,
                    "modified": delta.modified,
                    "removed": delta.removed,
                },
            ))

        await self.bus.publish(Event(
            event_type=EventType.INGESTION_COMPLETE,
            source="ingestion_service",
            data=results,
        ))

        logger.info(f"Full pipeline complete: {len(all_nodes)} nodes in {duration}s")
        return results

    async def run_single_domain(self, domain: str) -> Dict[str, Any]:
        """Run pipeline for a single EASA domain."""
        from crawler import EASA_DOMAINS, _scrape_xml_url_from_page, _download_to_domain, _domain_dir
        import os

        if domain not in EASA_DOMAINS:
            return {"error": f"Unknown domain: {domain}", "available": list(EASA_DOMAINS.keys())}

        page_url = EASA_DOMAINS[domain]
        xml_url = _scrape_xml_url_from_page(page_url)

        if not xml_url:
            # Task 6: LLM fallback would be invoked here
            return {"error": f"No XML download link found for {domain}"}

        _download_to_domain(xml_url, domain)

        # Find the downloaded XML
        domain_dir = _domain_dir(domain)
        xml_files = [f for f in os.listdir(domain_dir) if f.endswith(".xml")]
        if not xml_files:
            return {"error": f"No XML file found after download for {domain}"}

        xml_path = os.path.join(domain_dir, xml_files[0])
        nodes = self._parse_domain(domain, xml_path)

        return {
            "domain": domain,
            "nodes_parsed": len(nodes),
            "xml_path": xml_path,
            "status": "ok",
        }

    @staticmethod
    def _parse_domain(domain: str, xml_path: str) -> List[RegulatoryNode]:
        """Parse a single domain XML into RegulatoryNodes."""
        from ingestion.easa_parser import parse_easa_xml
        from ingestion.contracts import RegulatoryNode as ContractNode

        raw_nodes = parse_easa_xml(xml_path)
        if not raw_nodes:
            return []

        # Convert RegulationNode → RegulatoryNode (contracts format)
        from ingestion.hasher import generate_node_hash
        result: List[ContractNode] = []

        for rn in raw_nodes:
            result.append(ContractNode(
                node_id=rn.node_id,
                title=rn.node_id,
                content=rn.content,
                content_hash=rn.sha256_hash,
                node_type=rn.category,
                metadata={"domain": domain, "category": rn.category},
            ))

        return result
