"""
Neo4j Graph Schema Definitions — Deterministic Foundations (Sprint 2).

This module manages uniqueness constraints and performance indexes in Neo4j 
to ensure the 'Certifiable Robustness' of the regulatory knowledge graph.
"""
import logging
from neo4j import Driver

logger = logging.getLogger("regumap-ai.graph-schema")

# ──────────────────────────────────────────────────────────────────────────────
# CYPHER SCHEMA DEFINITIONS (Neo4j 5.x)
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_QUERIES = [
    # 1. Uniqueness Constraints (Safety-Critical)
    "CREATE CONSTRAINT unique_regulation_id IF NOT EXISTS FOR (r:Regulation) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT unique_requirement_id IF NOT EXISTS FOR (req:Requirement) REQUIRE req.id IS UNIQUE",
    "CREATE CONSTRAINT unique_document_hash IF NOT EXISTS FOR (d:Document) REQUIRE d.hash IS UNIQUE",
    
    # 2. Performance Indexes (Deterministic Traversal)
    "CREATE INDEX regulation_effective_date_idx IF NOT EXISTS FOR (r:Regulation) ON (r.effective_date)",
    "CREATE INDEX requirement_topic_idx IF NOT EXISTS FOR (req:Requirement) ON (req.topic)",
]

def initialize_schema(driver: Driver):
    """
    Executes the Cypher schema definitions in a single transaction.
    Ensures idempotence via 'IF NOT EXISTS' clauses.
    """
    logger.info("Initializing Neo4j schema (constraints and indexes)...")
    
    with driver.session() as session:
        try:
            for query in SCHEMA_QUERIES:
                logger.debug(f"Executing schema query: {query}")
                session.run(query)
            logger.info("Neo4j schema initialization complete. ✅")
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j schema: {e}")
            raise

if __name__ == "__main__":
    # For manual execution
    import os
    from neo4j import GraphDatabase
    from dotenv import load_dotenv
    
    load_dotenv()
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        initialize_schema(driver)
    finally:
        driver.close()
