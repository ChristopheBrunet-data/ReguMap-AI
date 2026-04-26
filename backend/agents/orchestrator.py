from __future__ import annotations
from typing import List, Dict, Optional, TypedDict, TYPE_CHECKING
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from backend.api_pkg.schemas import ValidationTrace, TraceabilityLog
from backend.agents.symbolic_validator import SymbolicValidator
from backend.agents.system_prompts import RESEARCHER_PROMPT, AUDITOR_PROMPT
from backend.security.presidio_engine import DataSanitizer
import logging
import time

logger = logging.getLogger(__name__)

class ComplianceState(TypedDict):
    """
    Immuable state for the Multi-Agent Compliance Orchestrator.
    Tracks the reasoning loop and validation results.
    """
    user_query: str
    sanitized_query: str
    researcher_response: str
    draft_response: str
    cited_references: List[str]
    validation_trace: Optional[ValidationTrace]
    traceability_log: Optional[TraceabilityLog]
    iteration_count: int
    error_log: List[str]

class ComplianceTimeoutError(Exception):
    """Raised when the agent loop fails to converge on a valid response."""
    pass

class ComplianceOrchestrator:
    """
    Lightweight state machine orchestrator for ReguMap-AI.
    Implements the Researcher -> Graph -> Auditor -> Validator -> Auto-Correction loop.
    """
    
    def __init__(self, validator: SymbolicValidator):
        self.validator = validator
        self.sanitizer = DataSanitizer()

    def run(self, query: str) -> ComplianceState:
        """
        Executes the full agentic loop for a given query.
        """
        # 0. Sanitize Query (PII Protection - Sprint 5)
        clean_query, _ = self.sanitizer.sanitize_prompt(query)
        
        state: ComplianceState = {
            "user_query": query,
            "sanitized_query": clean_query,
            "researcher_response": "",
            "draft_response": "",
            "cited_references": [],
            "validation_trace": None,
            "traceability_log": None,
            "iteration_count": 0,
            "error_log": []
        }
        
        while state["iteration_count"] < 3:
            state["iteration_count"] += 1
            logger.info(f"--- Iteration {state['iteration_count']} ---")
            
            # 1. Researcher Phase (Mocked LLM generation for now)
            # Use sanitized_query instead of raw user_query
            state = self.node_researcher(state)
            
            # 2. Auditor Phase (Mocked LLM drafting)
            state = self.node_auditor(state)
            
            # 3. Validation Phase (Deterministic Guardrail)
            v_start = time.time()
            state = self.node_validator(state)
            v_duration = (time.time() - v_start) * 1000 # ms
            
            # 4. Build Traceability Log
            if state["validation_trace"]:
                state["traceability_log"] = TraceabilityLog(
                    cypher_query_executed=state["validation_trace"].cypher_query_executed or "NO_QUERY",
                    node_hashes=state["validation_trace"].cryptographic_hashes,
                    validation_status=state["validation_trace"].is_valid,
                    anonymized=True, # Explicitly true per Sprint 5 requirements
                    execution_time_ms=round(v_duration, 2)
                )
            
            # 5. Route
            next_step = self.route_validation(state)
            
            if next_step == "END":
                logger.info("Validation Successful. Ending loop.")
                return state
            
            logger.warning(f"Validation failed. Retrying... Errors: {state['validation_trace'].error_message}")
            state["error_log"].append(state["validation_trace"].error_message)

        # If we reach here, we hit the iteration limit
        raise ComplianceTimeoutError(
            f"Failed to produce a certifiable response after {state['iteration_count']} attempts. "
            f"Last validation error: {state['validation_trace'].error_message if state['validation_trace'] else 'Unknown'}"
        )

    def node_researcher(self, state: ComplianceState) -> ComplianceState:
        """
        Agent: Researcher
        Task: Query the hybrid engine and extract context.
        """
        # MOCK IMPLEMENTATION of LLM - Using sanitized_query
        if state["error_log"]:
            state["researcher_response"] = "The correct requirement is Part-IS.AR.10"
        else:
            state["researcher_response"] = f"Analyzing context for: {state['sanitized_query']}. References: ADR.OR.B.005, HALLUCINATED.RULE"
            
        return state

    def node_auditor(self, state: ComplianceState) -> ComplianceState:
        """
        Agent: Auditor
        Task: Draft the final response using only researcher data.
        """
        state["draft_response"] = f"Based on the analysis: {state['researcher_response']}."
        return state

    def node_validator(self, state: ComplianceState) -> ComplianceState:
        """
        Agent: Validator (Deterministic)
        Task: Verify all drafted text against the Neo4j graph using Symbolic Validator.
        """
        trace = self.validator.validate_assertion(state["draft_response"])
        state["validation_trace"] = trace
        return state

    def route_validation(self, state: ComplianceState) -> str:
        """
        Decision Edge: Determines if the response is ready or needs correction.
        """
        if state["validation_trace"] and state["validation_trace"].is_valid:
            return "END"
        return "RESEARCHER"
