from neo4j import Driver
from typing import List, Dict, Optional

def verify_nodes_exist(driver: Driver, node_ids: List[str]) -> Dict[str, str]:
    """
    Deterministic Cypher query to verify existence and integrity of regulatory nodes.
    Returns a mapping of {node_id: content_hash} for all found nodes.
    
    This is the core of the Symbolic Validator.
    """
    if not node_ids:
        return {}

    query = """
    MATCH (n:Regulation)
    WHERE n.id IN $node_ids
    RETURN n.id AS node_id, n.content_hash AS content_hash
    UNION
    MATCH (n:Requirement)
    WHERE n.id IN $node_ids
    RETURN n.id AS node_id, n.content_hash AS content_hash
    UNION
    MATCH (n:Document)
    WHERE n.id IN $node_ids
    RETURN n.id AS node_id, n.content_hash AS content_hash
    UNION
    MATCH (n:RegulatoryNode)
    WHERE n.node_id IN $node_ids
    RETURN n.node_id AS node_id, n.content_hash AS content_hash
    """
    
    results_map = {}
    
    with driver.session() as session:
        records = session.run(query, node_ids=node_ids)
        for record in records:
            results_map[record["node_id"]] = record["content_hash"]
            
    return results_map


# ──────────────────────────────────────────────────────────────────────────────
# Impact Analysis Queries (Task 10)
# ──────────────────────────────────────────────────────────────────────────────

def find_impacted_manuals(driver: Driver, rule_ids: List[str]) -> List[Dict]:
    """
    Finds all ManualSection nodes linked to the given rule IDs via MANDATES edges.
    Used by the Watchdog to determine which operator manuals are affected by rule changes.

    Returns list of {rule_id, section_id, section_label, page_number}.
    """
    if not rule_ids:
        return []

    query = """
    MATCH (r:RegulatoryNode)-[:MANDATES]->(m:ManualSection)
    WHERE r.node_id IN $rule_ids
    RETURN r.node_id AS rule_id,
           m.section_id AS section_id,
           m.label AS section_label,
           m.page_number AS page_number
    """

    results = []
    with driver.session() as session:
        records = session.run(query, rule_ids=rule_ids)
        for record in records:
            results.append(dict(record))

    return results


def get_regulatory_chain(driver: Driver, rule_id: str, max_depth: int = 5) -> List[Dict]:
    """
    Returns the full regulatory ancestry of a rule via SUPERSEDES, REFERENCES, and CLARIFIES.
    Used for complete traceability in audit reports.

    Returns list of {node_id, node_type, relationship, depth}.
    """
    query = """
    MATCH path = (start:RegulatoryNode {node_id: $rule_id})-[r:SUPERSEDES|REFERENCES|CLARIFIES*1..5]->(target:RegulatoryNode)
    UNWIND relationships(path) AS rel
    WITH target, type(rel) AS rel_type, length(path) AS depth
    RETURN DISTINCT
           target.node_id AS node_id,
           target.node_type AS node_type,
           rel_type AS relationship,
           depth
    ORDER BY depth
    LIMIT 50
    """

    results = []
    with driver.session() as session:
        records = session.run(query, rule_id=rule_id)
        for record in records:
            results.append(dict(record))

    return results


def get_all_node_hashes(driver: Driver) -> Dict[str, str]:
    """
    Returns all RegulatoryNode hashes for graph diff computation.
    Used by IngestionService to detect changes.
    """
    query = """
    MATCH (n:RegulatoryNode)
    WHERE n.content_hash IS NOT NULL
    RETURN n.node_id AS node_id, n.content_hash AS content_hash
    """

    results = {}
    with driver.session() as session:
        records = session.run(query)
        for record in records:
            results[record["node_id"]] = record["content_hash"]

    return results
