"""
FastAPI Dependency Injection — Manages the ComplianceEngine singleton lifecycle.

The engine is heavy (FAISS indexes, BM25, HuggingFace embeddings, Knowledge Graph).
It must be initialized once at startup and shared across all requests.
This module provides the dependency injection layer for that.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from engine import ComplianceEngine
from graph.neo4j_schema import initialize_schema
from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Singleton Engine Instance
# ──────────────────────────────────────────────────────────────────────────────

_engine_instance: Optional[ComplianceEngine] = None
_neo4j_driver: Optional[Driver] = None


def get_engine() -> ComplianceEngine:
    """
    FastAPI dependency: returns the shared ComplianceEngine instance.

    Raises ValueError if the engine has not been initialized yet
    (i.e., startup didn't complete or API key is missing).
    """
    if _engine_instance is None:
        raise ValueError(
            "ComplianceEngine not initialized. "
            "Ensure GEMINI_API_KEY is set and the server started correctly."
        )
    return _engine_instance


def get_neo4j_driver() -> Driver:
    """
    FastAPI dependency: returns the active Neo4j driver or a Mock for local testing.
    """
    global _neo4j_driver
    if _neo4j_driver is None:
        logger.warning("Neo4j not available. Falling back to MockDriver for demonstration.")
        return MockNeo4jDriver()
    return _neo4j_driver

class MockNeo4jDriver:
    """Mock for local dev without Docker."""
    def __init__(self):
        self.db = {
            "CAT.IDE.A.190": "sha256_7f8e9a0b1c2d3e4f5a6b7c8d9e0f",
            "ADR.OR.B.005": "sha256_1a2b3c4d5e6f7g8h9i0j",
            "Part-IS.AR.10": "sha256_k1l2m3n4o5p6q7r8s9t0"
        }
    def session(self, **kwargs): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def verify_connectivity(self): pass
    def close(self): pass
    def run(self, query, node_ids=None, **kwargs):
        results = []
        if node_ids:
            for nid in node_ids:
                if nid in self.db:
                    results.append({"node_id": nid, "node_hash": self.db[nid]})
        return results


def initialize_engine(api_key: Optional[str] = None) -> ComplianceEngine:
    """
    Initialize the ComplianceEngine singleton.

    Called once during FastAPI startup. The engine is heavy — initialization
    loads FAISS indexes, BM25, and the knowledge graph from disk.
    """
    global _engine_instance

    if _engine_instance is not None:
        logger.warning("Engine already initialized, returning existing instance.")
        return _engine_instance

    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is required. "
            "Set it in your .env file or pass it to initialize_engine()."
        )

    logger.info("Initializing ComplianceEngine...")
    model_name = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash")
    _engine_instance = ComplianceEngine(api_key=key, model_name=model_name)
    logger.info(f"ComplianceEngine initialized successfully with model: {model_name}")

    # 2. Initialize Neo4j Schema
    initialize_neo4j_schema()
    
    return _engine_instance

def initialize_neo4j_schema():
    """Connects to Neo4j and applies constraints/indexes."""
    global _neo4j_driver
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    try:
        logger.info(f"Connecting to Neo4j at {uri}...")
        _neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
        # Verify connectivity
        _neo4j_driver.verify_connectivity()
        
        # Apply schema
        initialize_schema(_neo4j_driver)
    except Exception as e:
        logger.error(f"Neo4j schema initialization failed: {e}")
        # We don't necessarily want to crash the whole engine if Neo4j is down,
        # but for Sprint 2 it might be better to know.
        if _neo4j_driver:
            _neo4j_driver.close()
            _neo4j_driver = None


def shutdown_engine():
    """Clean up engine resources on shutdown."""
    global _engine_instance, _neo4j_driver
    if _engine_instance is not None:
        logger.info("Shutting down ComplianceEngine.")
        _engine_instance = None
    
    if _neo4j_driver is not None:
        logger.info("Closing Neo4j driver.")
        _neo4j_driver.close()
        _neo4j_driver = None


def is_engine_ready() -> bool:
    """Check if the engine is initialized and has data loaded."""
    return _engine_instance is not None
