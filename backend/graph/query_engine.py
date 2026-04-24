from neo4j import Driver
from typing import List, Dict

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
    """
    
    results_map = {}
    
    with driver.session() as session:
        records = session.run(query, node_ids=node_ids)
        for record in records:
            results_map[record["node_id"]] = record["content_hash"]
            
    return results_map
