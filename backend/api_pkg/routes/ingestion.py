"""
Ingestion Routes — Manages document loading and index building.

GET  /api/v1/ingest/status       — Current ingestion state
POST /api/v1/ingest/easa         — Load EASA XML rules
POST /api/v1/ingest/manual       — Upload operator manual (PDF)
POST /api/v1/ingest/prefilter    — Run semantic pre-filtering
"""

from __future__ import annotations

import logging
import os
import tempfile
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api_pkg.dependencies import get_engine
from api_pkg.schemas import ErrorResponse, IngestionStatusResponse
from engine import ComplianceEngine
from ingestion.easa_parser import parse_easa_xml
from ingestion.manual_parser import ManualPdfParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingestion"])


@router.get(
    "/status",
    response_model=IngestionStatusResponse,
    summary="Ingestion status",
    description="Returns the current state of data loading and index building.",
)
async def ingestion_status(
    engine: ComplianceEngine = Depends(get_engine),
):
    return IngestionStatusResponse(
        easa_rules_count=len(engine._all_rules),
        manual_chunks_count=len(engine.manual_chunks),
        pre_filtered=engine.pre_filtered,
        graph_built=engine.knowledge_graph.is_built(),
    )


@router.post(
    "/easa",
    response_model=IngestionStatusResponse,
    summary="Load EASA rules from XML",
    description="Parses an EASA Easy Access Rules XML file and builds the rule index.",
)
async def ingest_easa_xml(
    file: UploadFile = File(..., description="EASA XML file"),
    engine: ComplianceEngine = Depends(get_engine),
):
    if not file.filename or not file.filename.endswith(".xml"):
        raise HTTPException(status_code=422, detail="File must be an XML file.")

    # Save uploaded file to a temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        logger.info(f"Ingesting EASA XML: {file.filename} ({len(content)} bytes)")
        raw_nodes = parse_easa_xml(tmp_path)

        if not raw_nodes:
            raise HTTPException(
                status_code=422,
                detail="No EASA requirements found in the uploaded XML.",
            )

        # Convert RegulationNode to EasaRequirement for the engine
        from schemas import EasaRequirement
        rules = [
            EasaRequirement(
                id=node.node_id,
                text=node.content,
                type=node.category,
                source_title=node.node_id, # Fallback
                amc_gm_info="Hard Law" if node.category in ["Regulation", "IR"] else "Soft Law"
            )
            for node in raw_nodes
        ]

        engine.build_rule_index(rules)
        logger.info(f"EASA ingestion complete: {len(rules)} rules indexed.")
    finally:
        os.unlink(tmp_path)

    return IngestionStatusResponse(
        easa_rules_count=len(engine._all_rules),
        manual_chunks_count=len(engine.manual_chunks),
        pre_filtered=engine.pre_filtered,
        graph_built=engine.knowledge_graph.is_built(),
    )


@router.post(
    "/manual",
    response_model=IngestionStatusResponse,
    summary="Upload operator manual (PDF)",
    description="Parses a PDF operator manual and loads chunks for compliance auditing.",
)
async def ingest_manual_pdf(
    file: UploadFile = File(..., description="PDF operator manual"),
    engine: ComplianceEngine = Depends(get_engine),
):
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=422, detail="File must be a PDF file.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        logger.info(f"Ingesting manual PDF: {file.filename} ({len(content)} bytes)")
        parser = ManualPdfParser(tmp_path)
        chunks = list(parser.parse())

        if not chunks:
            raise HTTPException(
                status_code=422,
                detail="No content extracted from the uploaded PDF.",
            )

        engine.set_manual_chunks(chunks)
        logger.info(f"Manual ingestion complete: {len(chunks)} chunks loaded.")
    finally:
        os.unlink(tmp_path)

    return IngestionStatusResponse(
        easa_rules_count=len(engine._all_rules),
        manual_chunks_count=len(engine.manual_chunks),
        pre_filtered=engine.pre_filtered,
        graph_built=engine.knowledge_graph.is_built(),
    )


@router.post(
    "/prefilter",
    response_model=IngestionStatusResponse,
    summary="Run semantic pre-filtering",
    description=(
        "Runs inverted vector search to map manual chunks to EASA rules. "
        "Must be called after uploading both EASA rules and a manual."
    ),
)
async def run_prefilter(
    engine: ComplianceEngine = Depends(get_engine),
):
    if not engine.vectorstore:
        raise HTTPException(
            status_code=503,
            detail="EASA rule index not built. Upload EASA XML first.",
        )
    if not engine.manual_chunks:
        raise HTTPException(
            status_code=503,
            detail="No manual chunks loaded. Upload a manual PDF first.",
        )

    logger.info("Running semantic pre-filtering...")
    start = time.time()
    engine.run_semantic_pre_filtering()
    duration = time.time() - start
    logger.info(f"Pre-filtering complete in {duration:.1f}s")

    return IngestionStatusResponse(
        easa_rules_count=len(engine._all_rules),
        manual_chunks_count=len(engine.manual_chunks),
        pre_filtered=engine.pre_filtered,
        graph_built=engine.knowledge_graph.is_built(),
    )
