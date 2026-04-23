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

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Singleton Engine Instance
# ──────────────────────────────────────────────────────────────────────────────

_engine_instance: Optional[ComplianceEngine] = None


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
    return _engine_instance


def shutdown_engine():
    """Clean up engine resources on shutdown."""
    global _engine_instance
    if _engine_instance is not None:
        logger.info("Shutting down ComplianceEngine.")
        _engine_instance = None


def is_engine_ready() -> bool:
    """Check if the engine is initialized and has data loaded."""
    return _engine_instance is not None
