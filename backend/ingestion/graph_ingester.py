import os
import sys
import logging
from typing import List
from neo4j import GraphDatabase

# Ensure schemas are accessible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from schemas import RegulationNode

logger = logging.getLogger("regumap-ai.ingester")
logging.basicConfig(level=logging.INFO)

class GraphIngester:
    """
    Handles the batch insertion of regulatory nodes into Neo4j.
    Enforces referential integrity through MERGE statements.
    """
    def __init__(self, uri=None, user=None, password=None):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        
    def close(self):
        self.driver.close()
        
    def batch_insert(self, nodes: List[RegulationNode]):
        """
        Executes a batch MERGE operation to insert or update RegulationNodes.
        Requires the nodes to strictly conform to the RegulationNode Pydantic schema.
        """
        if not nodes:
            logger.warning("No nodes provided for ingestion.")
            return

        query = """
        UNWIND $batch AS row
        MERGE (r:Regulation {id: row.node_id})
        SET r.content = row.content,
            r.category = row.category,
            r.sha256_hash = row.sha256_hash
        """
        
        # Convert Pydantic objects to dicts for the Cypher parameter
        batch_data = [node.model_dump() for node in nodes]
        
        with self.driver.session() as session:
            try:
                result = session.run(query, batch=batch_data)
                info = result.consume().counters
                logger.info(f"Ingestion complete: {info.nodes_created} nodes created, "
                            f"{info.properties_set} properties set.")
            except Exception as e:
                logger.error(f"Failed to execute batch ingestion: {e}")
                raise

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    # Simple test of the logic
    dummy_node = RegulationNode(
        node_id="TEST.001",
        content="This is a dummy regulation.",
        category="IR",
        sha256_hash="dummy_hash_12345"
    )
    
    ingester = GraphIngester()
    try:
        # Note: If neo4j is not running locally, this will fail.
        ingester.batch_insert([dummy_node])
    except Exception as e:
        print(f"Could not reach database (expected in isolated tests): {e}")
    finally:
        ingester.close()
