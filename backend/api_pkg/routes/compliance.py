"""
Compliance Audit Routes — Exposes the 4-agent pipeline via HTTP.

POST /api/v1/audit/compliance   — Single requirement audit
POST /api/v1/audit/batch        — Batch audit (up to 50 rules)

These endpoints wrap ComplianceEngine.evaluate_compliance(), which runs
the full 4-agent pipeline (Researcher → Conflict → Auditor → Critic).
"""

from __future__ import annotations

import logging
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api_pkg.schemas import (
    AuditRequest,
    AuditResultResponse,
    AuditStatusResponse,
    BatchAuditRequest,
    BatchAuditResponse,
    ComplianceResponse,
    ErrorResponse,
    TraceabilityLog,
)
from engine import ComplianceEngine
from agents.orchestrator import ComplianceOrchestrator
from agents.symbolic_validator import SymbolicValidator
from api_pkg.dependencies import get_engine, get_neo4j_driver
from neo4j import Driver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Compliance Audit"])


@router.post(
    "/ask",
    response_model=ComplianceResponse,
    summary="Ask a certifiable regulatory question",
    description=(
        "Advanced Q&A endpoint using the Multi-Agent Orchestrator. "
        "Every response is cross-checked by the Symbolic Validator against Neo4j. "
        "Includes a full traceability_log for XAI compliance."
    ),
)
async def ask_compliance(
    query: str,
    engine: ComplianceEngine = Depends(get_engine),
    driver: Driver = Depends(get_neo4j_driver),
):
    """Certifiable Q&A via orchestrator loop."""
    validator = SymbolicValidator(driver)
    orchestrator = ComplianceOrchestrator(engine, validator)

    try:
        state = orchestrator.run(query)
        
        return ComplianceResponse(
            answer=state["draft_response"],
            cited_references=state["cited_references"],
            traceability_log=state["traceability_log"],
            is_valid=state["validation_trace"].is_valid,
            iterations=state["iteration_count"]
        )
    except Exception as e:
        logger.error(f"Orchestration failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Compliance Orchestration Error: {str(e)}"
        )


@router.post(
    "/compliance",
    response_model=AuditResultResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Pipeline error"},
        503: {"model": ErrorResponse, "description": "Engine not ready"},
    },
    summary="Run a single compliance audit",
    description=(
        "Runs the full 4-agent compliance pipeline (Researcher → Conflict Detector → "
        "Auditor → Critic) for a single EASA requirement against the loaded manual. "
        "Returns the audit result with evidence coordinates, confidence score, "
        "and agent trace for full traceability."
    ),
)
async def audit_compliance(
    request: AuditRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    """Single-requirement compliance audit via the 4-agent pipeline."""

    if not engine.pre_filtered:
        raise HTTPException(
            status_code=503,
            detail=(
                "Engine not ready: manual chunks not loaded or pre-filtering not run. "
                "Upload a manual and call /api/v1/ingest/prefilter first."
            ),
        )

    # Verify the requirement exists in the index
    requirement = engine._rule_lookup.get(request.requirement_id)
    if requirement is None:
        raise HTTPException(
            status_code=404,
            detail=f"Requirement '{request.requirement_id}' not found in the EASA rule index.",
        )

    logger.info(f"Audit request: {request.requirement_id}")
    start = time.time()

    try:
        result = engine.evaluate_compliance(
            requirement=requirement,
            refined_question=request.refined_question,
        )
    except Exception as e:
        logger.error(f"Audit pipeline failed for {request.requirement_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Audit pipeline error: {str(e)[:300]}",
        )

    duration = time.time() - start
    logger.info(
        f"Audit complete: {request.requirement_id} → "
        f"{result.status} ({result.confidence_score:.2f}) in {duration:.1f}s"
    )

    return AuditResultResponse(
        requirement_id=result.requirement_id,
        status=AuditStatusResponse(result.status.value if hasattr(result.status, 'value') else result.status),
        evidence_quote=result.evidence_quote,
        source_reference=result.source_reference,
        confidence_score=result.confidence_score,
        suggested_fix=result.suggested_fix,
        cross_refs_used=result.cross_refs_used,
        validation_score=result.validation_score,
        evidence_crop_path=result.evidence_crop_path,
        agent_trace=result.agent_trace,
    )


@router.post(
    "/batch",
    response_model=BatchAuditResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Engine not ready"},
    },
    summary="Run a batch compliance audit",
    description=(
        "Audits multiple EASA requirements sequentially. "
        "Maximum 50 requirements per batch. Returns aggregate statistics."
    ),
)
async def batch_audit(
    request: BatchAuditRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    """Batch compliance audit — sequential execution of multiple requirements."""

    if not engine.pre_filtered:
        raise HTTPException(
            status_code=503,
            detail="Engine not ready: pre-filtering not run.",
        )

    logger.info(f"Batch audit request: {len(request.requirement_ids)} requirements")
    start = time.time()

    results: List[AuditResultResponse] = []
    counters = {"Compliant": 0, "Partial": 0, "Gap": 0, "Requires Human Review": 0}

    for req_id in request.requirement_ids:
        requirement = engine._rule_lookup.get(req_id)
        if requirement is None:
            # Skip unknown requirements with a warning result
            results.append(AuditResultResponse(
                requirement_id=req_id,
                status=AuditStatusResponse.REQUIRES_HUMAN_REVIEW,
                evidence_quote=f"Requirement '{req_id}' not found in index.",
                source_reference="N/A",
                confidence_score=0.0,
                agent_trace="SKIP: Requirement not found in EASA rule index.",
            ))
            counters["Requires Human Review"] += 1
            continue

        try:
            result = engine.evaluate_compliance(
                requirement=requirement,
                refined_question=request.refined_question,
            )
            status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
            results.append(AuditResultResponse(
                requirement_id=result.requirement_id,
                status=AuditStatusResponse(status_str),
                evidence_quote=result.evidence_quote,
                source_reference=result.source_reference,
                confidence_score=result.confidence_score,
                suggested_fix=result.suggested_fix,
                cross_refs_used=result.cross_refs_used,
                validation_score=result.validation_score,
                evidence_crop_path=result.evidence_crop_path,
                agent_trace=result.agent_trace,
            ))
            if status_str in counters:
                counters[status_str] += 1
        except Exception as e:
            logger.error(f"Batch audit failed for {req_id}: {e}")
            results.append(AuditResultResponse(
                requirement_id=req_id,
                status=AuditStatusResponse.REQUIRES_HUMAN_REVIEW,
                evidence_quote=f"Pipeline error: {str(e)[:200]}",
                source_reference="System Error",
                confidence_score=0.0,
                agent_trace=f"SELF-HEAL: {type(e).__name__}",
            ))
            counters["Requires Human Review"] += 1

    duration = time.time() - start
    logger.info(f"Batch audit complete: {len(results)} results in {duration:.1f}s")

    return BatchAuditResponse(
        results=results,
        total=len(results),
        compliant=counters["Compliant"],
        partial=counters["Partial"],
        gaps=counters["Gap"],
        requires_review=counters["Requires Human Review"],
        duration_seconds=round(duration, 2),
    )
