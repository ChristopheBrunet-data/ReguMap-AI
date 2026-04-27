"""
Compliance Audit Routes — Exposes the 5-agent pipeline via HTTP.

POST /api/v1/audit/ask          — Certifiable Q&A via orchestrator loop
POST /api/v1/audit/compliance   — Single requirement audit
POST /api/v1/audit/batch        — Batch audit (up to 50 rules)
POST /api/v1/audit/report       — Batch audit + PDF report generation

These endpoints wrap ComplianceEngine.evaluate_compliance(), which runs
the full 5-agent pipeline (Researcher → Conflict → Auditor → Critic → SymbolicValidator).
"""

import logging
import os
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
    QARequest,
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
    request: QARequest,
    engine: ComplianceEngine = Depends(get_engine),
    driver: Driver = Depends(get_neo4j_driver),
):
    """Certifiable Q&A via orchestrator loop."""
    query = request.question
    validator = SymbolicValidator(driver)
    orchestrator = ComplianceOrchestrator(validator)

    try:
        state = orchestrator.run(query)
        
        return ComplianceResponse(
            answer=state.draft_response,
            cited_references=state.cited_references,
            traceability_log=state.traceability_log,
            is_valid=state.validation_trace.is_valid,
            iterations=state.iteration_count
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
        "Runs the full 5-agent compliance pipeline (Researcher → Conflict Detector → "
        "Auditor → Critic → SymbolicValidator) for a single EASA requirement. "
        "Returns the audit result with evidence coordinates, confidence score, "
        "and agent trace for full traceability."
    ),
)
async def audit_compliance(
    request: AuditRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    """Single-requirement compliance audit via the 5-agent pipeline."""

    if not engine.pre_filtered:
        raise HTTPException(
            status_code=503,
            detail=(
                "Engine not ready: manual chunks not loaded or pre-filtering not run. "
                "Upload a manual and call /api/v1/ingest/prefilter first."
            ),
        )

    requirement = engine.get_requirement(request.requirement_id)
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
        "Audits multiple EASA requirements concurrently (bounded parallelism). "
        "Maximum 50 requirements per batch. Returns aggregate statistics."
    ),
)
async def batch_audit(
    request: BatchAuditRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    """Batch compliance audit — concurrent execution with bounded parallelism."""

    if not engine.pre_filtered:
        raise HTTPException(
            status_code=503,
            detail="Engine not ready: pre-filtering not run.",
        )

    logger.info(f"Batch audit request: {len(request.requirement_ids)} requirements")
    start = time.time()

    import asyncio

    MAX_CONCURRENT = 3
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _audit_one(req_id: str) -> AuditResultResponse:
        async with semaphore:
            requirement = engine.get_requirement(req_id)
            if requirement is None:
                return AuditResultResponse(
                    requirement_id=req_id,
                    status=AuditStatusResponse.REQUIRES_HUMAN_REVIEW,
                    evidence_quote=f"Requirement '{req_id}' not found in index.",
                    source_reference="N/A",
                    confidence_score=0.0,
                    agent_trace="SKIP: Requirement not found in EASA rule index.",
                )

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: engine.evaluate_compliance(
                        requirement=requirement,
                        refined_question=request.refined_question,
                    ),
                )
                status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
                return AuditResultResponse(
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
                )
            except Exception as e:
                logger.error(f"Batch audit failed for {req_id}: {e}")
                return AuditResultResponse(
                    requirement_id=req_id,
                    status=AuditStatusResponse.REQUIRES_HUMAN_REVIEW,
                    evidence_quote=f"Pipeline error: {str(e)[:200]}",
                    source_reference="System Error",
                    confidence_score=0.0,
                    agent_trace=f"SELF-HEAL: {type(e).__name__}",
                )

    results = await asyncio.gather(
        *[_audit_one(req_id) for req_id in request.requirement_ids]
    )

    counters = {"Compliant": 0, "Partial": 0, "Gap": 0, "Requires Human Review": 0}
    for r in results:
        status_str = r.status.value if hasattr(r.status, 'value') else str(r.status)
        if status_str in counters:
            counters[status_str] += 1

    duration = time.time() - start
    logger.info(f"Batch audit complete: {len(results)} results in {duration:.1f}s")

    return BatchAuditResponse(
        results=list(results),
        total=len(results),
        compliant=counters["Compliant"],
        partial=counters["Partial"],
        gaps=counters["Gap"],
        requires_review=counters["Requires Human Review"],
        duration_seconds=round(duration, 2),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Report Generation (Task 12)
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/report",
    summary="Generate PDF compliance report",
    description=(
        "Runs a batch audit and generates a formal PDF compliance report "
        "suitable for DO-326A review."
    ),
)
async def generate_report(
    request: BatchAuditRequest,
    engine: ComplianceEngine = Depends(get_engine),
):
    """Runs batch audit then generates PDF report."""
    from fastapi.responses import FileResponse

    if not engine.pre_filtered:
        raise HTTPException(status_code=503, detail="Engine not ready.")

    import asyncio

    MAX_CONCURRENT = 3
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _audit_one(req_id: str):
        async with semaphore:
            requirement = engine.get_requirement(req_id)
            if requirement is None:
                return {
                    "requirement_id": req_id,
                    "status": "Requires Human Review",
                    "evidence_quote": f"Requirement '{req_id}' not found.",
                    "source_reference": "N/A",
                    "confidence_score": 0.0,
                }
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: engine.evaluate_compliance(
                        requirement=requirement,
                        refined_question=request.refined_question,
                    ),
                )
                return {
                    "requirement_id": result.requirement_id,
                    "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                    "evidence_quote": result.evidence_quote,
                    "source_reference": result.source_reference,
                    "confidence_score": result.confidence_score,
                    "suggested_fix": result.suggested_fix,
                    "cross_refs_used": result.cross_refs_used,
                    "agent_trace": result.agent_trace,
                }
            except Exception as e:
                return {
                    "requirement_id": req_id,
                    "status": "Requires Human Review",
                    "evidence_quote": f"Error: {str(e)[:200]}",
                    "source_reference": "System Error",
                    "confidence_score": 0.0,
                }

    results = await asyncio.gather(
        *[_audit_one(req_id) for req_id in request.requirement_ids]
    )

    from services.report_generator import generate_audit_report
    pdf_path = generate_audit_report(list(results))

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=os.path.basename(pdf_path),
    )
