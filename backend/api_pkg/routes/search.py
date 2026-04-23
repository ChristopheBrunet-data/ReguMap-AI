"""
Search & Q&A Routes — Exposes hybrid search and regulatory Q&A via HTTP.

POST /api/v1/search   — Hybrid search (FAISS + BM25 + Graph)
POST /api/v1/qa       — Regulatory question answering
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api_pkg.dependencies import get_engine
from api_pkg.schemas import (
    QARequest,
    QAResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from engine import ComplianceEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search & Q&A"])


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid regulatory search",
    description="Searches EASA rules using FAISS + BM25 + Graph traversal.",
)
async def search_rules(
    request: SearchRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    if not engine.vectorstore:
        raise HTTPException(status_code=503, detail="Rule index not built.")

    results = engine.hybrid_search(
        query=request.query,
        k=request.k,
        domain_filter=request.domain_filter,
    )

    items = [
        SearchResultItem(
            rule_id=rule.id,
            text=rule.text[:500],
            source_title=rule.source_title,
            domain=rule.domain,
            score=score,
        )
        for rule, score in results
    ]

    return SearchResponse(results=items, total=len(items), query=request.query)


@router.post(
    "/qa",
    response_model=QAResponse,
    summary="Regulatory Q&A",
    description="Answers regulatory questions using hybrid retrieval + LLM.",
)
async def regulatory_qa(
    request: QARequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    if not engine.vectorstore:
        raise HTTPException(status_code=503, detail="Rule index not built.")

    try:
        answer = engine.answer_regulatory_question(
            question=request.question,
            domain_filter=request.domain_filter,
        )
    except Exception as e:
        logger.error(f"Q&A failed: {e}")
        raise HTTPException(status_code=500, detail=f"Q&A error: {str(e)[:300]}")

    # Get sources for the response
    search_results = engine.hybrid_search(request.question, k=3, domain_filter=request.domain_filter)
    sources = [
        SearchResultItem(
            rule_id=rule.id,
            text=rule.text[:300],
            source_title=rule.source_title,
            domain=rule.domain,
            score=score,
        )
        for rule, score in search_results
    ]

    return QAResponse(answer=answer, sources=sources)
