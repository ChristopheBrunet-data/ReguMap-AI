"""
Idempotent Persistence Layer for Neo4j — T1.2 (Sprint 1)
Ensures 'Certifiable Robustness' via batching (UNWIND) and atomic upserts (MERGE).
"""

import logging
from typing import List, Dict, Any
from collections import defaultdict
from neo4j import Driver
from ingestion.contracts import RegulatoryNode, RegulatoryEdgeType

logger = logging.getLogger("regumap-ai.graph-persistence")

def upsert_nodes_to_neo4j(driver: Driver, nodes: List[RegulatoryNode], batch_size: int = 500):
    """
    Persists a batch of RegulatoryNodes to Neo4j using MERGE for idempotence.
    Uses UNWIND for high-performance batching.
    """
    if not nodes:
        return

    # 1. Preparation of the batch data
    batch = []
    for node in nodes:
        batch.append({
            "node_id": node.node_id,
            "properties": {
                "title": node.title,
                "content": node.content,
                "content_hash": node.content_hash,
                "node_type": node.node_type,
                "parent_id": node.parent_id,
                **node.metadata
            }
        })

    # 2. Cypher Query (Idempotent Upsert)
    query = """
    UNWIND $batch AS row
    MERGE (n:RegulatoryNode {node_id: row.node_id})
    SET n += row.properties,
        n.updated_at = datetime()
    """

    # 3. Execution in a write transaction
    try:
        with driver.session() as session:
            for i in range(0, len(batch), batch_size):
                current_batch = batch[i:i + batch_size]
                session.execute_write(lambda tx: tx.run(query, batch=current_batch))
                logger.info(f"Upserted {len(current_batch)} nodes to Neo4j.")
    except Exception as e:
        logger.error(f"Failed to upsert nodes to Neo4j: {e}")
        raise


def upsert_edges_to_neo4j(driver: Driver, edges: List[Dict[str, Any]], batch_size: int = 500):
    """
    Persists a batch of relationships to Neo4j using native relationship labels (T1.3).
    Groups edges by type to work around Cypher parameter limitations for labels.
    """
    if not edges:
        return

    # 1. Grouping by type (T1.3.2)
    by_type = defaultdict(list)
    for edge in edges:
        edge_type = edge.get("type", "REFERENCES")
        
        # Validation of the type against the Enum (T1.3.1)
        try:
            valid_type = RegulatoryEdgeType(edge_type).value
            by_type[valid_type].append(edge)
        except ValueError:
            logger.warning(f"Relation ignorée : type '{edge_type}' non reconnu par l'ontologie.")

    # 2. Iteration on each type to perform native injection (T1.3.3)
    try:
        with driver.session() as session:
            for edge_label, batch in by_type.items():
                # Cypher Query with native label injection
                # Safe because edge_label is validated by RegulatoryEdgeType
                query = f"""
                UNWIND $batch AS row
                MATCH (source:RegulatoryNode {{node_id: row.source_id}})
                MATCH (target:RegulatoryNode {{node_id: row.target_id}})
                MERGE (source)-[r:{edge_label}]->(target)
                SET r.weight = row.weight,
                    r.updated_at = datetime()
                """
                
                for i in range(0, len(batch), batch_size):
                    current_batch = batch[i:i + batch_size]
                    # We use default arguments in lambda to capture current loop values (closure fix)
                    session.execute_write(
                        lambda tx, q=query, b=current_batch: tx.run(q, batch=b)
                    )
                    logger.info(f"Upserted {len(current_batch)} relationships of type {edge_label} to Neo4j.")
    except Exception as e:
        logger.error(f"Failed to upsert edges to Neo4j: {e}")
        raise
