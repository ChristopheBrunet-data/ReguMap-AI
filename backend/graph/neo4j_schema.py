"""
Neo4j Graph Schema Definitions — Deterministic Foundations (Sprint 2).

This module manages uniqueness constraints and performance indexes in Neo4j 
to ensure the 'Certifiable Robustness' of the regulatory knowledge graph.
It implements the DO-326A determinism via Cypher enforcement.
"""
import os
import logging
from neo4j import AsyncDriver, AsyncGraphDatabase

logger = logging.getLogger("regumap-ai.graph-schema")
logging.basicConfig(level=logging.INFO)

async def init_schema_async(driver: AsyncDriver):
    """
    Executes the Cypher schema definitions from init_schema.cypher asynchronously.
    """
    logger.info("Initializing Neo4j schema from init_schema.cypher...")
    schema_path = os.path.join(os.path.dirname(__file__), "init_schema.cypher")
    
    if not os.path.exists(schema_path):
        logger.error(f"Schema file not found at {schema_path}")
        return
        
    with open(schema_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Remove single line comments
    lines = content.splitlines()
    clean_lines = [line for line in lines if not line.strip().startswith("//")]
    clean_content = "\n".join(clean_lines)
    
    queries = [q.strip() for q in clean_content.split(';') if q.strip()]
    
    async with driver.session() as session:
        try:
            for query in queries:
                logger.info(f"Executing schema query: {query}")
                await session.run(query)
                
            # Verify constraints
            result = await session.run("SHOW CONSTRAINTS")
            records = await result.data()
            logger.info(f"Current constraints: {len(records)} found.")
            
            logger.info("Neo4j schema initialization complete. ✅")
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j schema: {e}")
            raise

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    
    load_dotenv()
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    async def main():
        driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        try:
            await init_schema_async(driver)
        finally:
            await driver.close()
            
    asyncio.run(main())
