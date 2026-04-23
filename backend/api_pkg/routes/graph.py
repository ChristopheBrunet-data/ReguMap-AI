"""
Knowledge Graph Routes — Exposes graph traversal and stats via HTTP.

GET  /api/v1/graph/stats      — Graph statistics
POST /api/v1/graph/traverse   — BFS traversal from a node
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_engine
from api.schemas import (
    GraphNodeResponse,
    GraphStatsResponse,
    GraphTraverseRequest,
    GraphTraverseResponse,
)
from engine import ComplianceEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


@router.get(
    "/stats",
    response_model=GraphStatsResponse,
    summary="Graph statistics",
    description="Returns node/edge counts, type distributions, and density.",
)
async def graph_stats(
    engine: ComplianceEngine = Depends(get_engine),
):
    kg = engine.knowledge_graph
    if not kg.is_built():
        raise HTTPException(status_code=503, detail="Knowledge graph not built.")

    stats = kg.get_stats()
    return GraphStatsResponse(
        total_nodes=stats.get("total_nodes", 0),
        total_edges=stats.get("total_edges", 0),
        node_types=stats.get("node_types", {}),
        edge_types=stats.get("edge_types", {}),
        density=stats.get("density", 0.0),
    )


@router.post(
    "/traverse",
    response_model=GraphTraverseResponse,
    summary="BFS graph traversal",
    description="Traverses the regulatory graph from a starting node using BFS.",
)
async def graph_traverse(
    request: GraphTraverseRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    kg = engine.knowledge_graph
    if not kg.is_built():
        raise HTTPException(status_code=503, detail="Knowledge graph not built.")

    results = kg.traverse(request.node_id, depth=request.depth)

    nodes = [
        GraphNodeResponse(
            id=r["id"],
            node_type=r.get("node_type"),
            label=r.get("label"),
            hop=r.get("hop", 0),
            properties=r.get("properties", {}),
        )
        for r in results
    ]

    return GraphTraverseResponse(
        root=request.node_id,
        depth=request.depth,
        nodes=nodes,
        total=len(nodes),
    )
