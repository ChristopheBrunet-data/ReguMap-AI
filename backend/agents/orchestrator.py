from typing import List, Dict, Optional, TypedDict
from api_pkg.schemas import ValidationTrace
from agents.symbolic_validator import SymbolicValidator
from engine import ComplianceEngine
import logging

logger = logging.getLogger(__name__)

class ComplianceState(TypedDict):
    """
    Immuable state for the Multi-Agent Compliance Orchestrator.
    Tracks the reasoning loop and validation results.
    """
    user_query: str
    draft_response: str
    cited_references: List[str]
    validation_trace: Optional[ValidationTrace]
    iteration_count: int
    error_log: List[str]

class ComplianceTimeoutError(Exception):
    """Raised when the agent loop fails to converge on a valid response."""
    pass

class ComplianceOrchestrator:
    """
    Lightweight state machine orchestrator for ReguMap-AI.
    Implements the Researcher -> Validator -> Auto-Correction loop.
    """
    
    def __init__(self, engine: ComplianceEngine, validator: SymbolicValidator):
        self.engine = engine
        self.validator = validator

    def run(self, query: str) -> ComplianceState:
        """
        Executes the full agentic loop for a given query.
        """
        state: ComplianceState = {
            "user_query": query,
            "draft_response": "",
            "cited_references": [],
            "validation_trace": None,
            "iteration_count": 0,
            "error_log": []
        }
        
        while state["iteration_count"] < 3:
            state["iteration_count"] += 1
            logger.info(f"--- Iteration {state['iteration_count']} ---")
            
            # 1. Research & Draft
            state = self.node_researcher(state)
            
            # 2. Validate citations
            state = self.node_validator(state)
            
            # 3. Route
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
        Task: Query the hybrid engine and draft a response with citations.
        """
        # In a real scenario, we use the engine to call Gemini
        # For T4.2, we integrate the engine's capability
        # We add a specific instruction to the prompt to list citations clearly
        
        # We'll use a simplified version for now, assuming the engine handles the prompt
        # but we might need to extract the IDs from the response.
        
        prompt_with_history = state["user_query"]
        if state["error_log"]:
            # Feed back the validation errors to the LLM
            history = "\n".join([f"- {err}" for err in state["error_log"]])
            prompt_with_history += f"\n\n[CRITICAL: PREVIOUS ATTEMPT FAILED VALIDATION]\nPlease correct the following errors and EXCLUDE these invalid references:\n{history}"

        # Call engine
        response_text = self.engine.answer_regulatory_question(prompt_with_history)
        
        # Extract cited IDs (Simple regex for EASA/S1000D patterns)
        import re
        from core_constants import EASA_RULE_ID_PATTERN
        
        found_ids = EASA_RULE_ID_PATTERN.findall(response_text)
        
        state["draft_response"] = response_text
        state["cited_references"] = list(set(found_ids))
        
        return state

    def node_validator(self, state: ComplianceState) -> ComplianceState:
        """
        Agent: Validator (Deterministic)
        Task: Verify all cited IDs against the Neo4j graph.
        """
        trace = self.validator.validate_references(state["cited_references"])
        state["validation_trace"] = trace
        return state

    def route_validation(self, state: ComplianceState) -> str:
        """
        Decision Edge: Determines if the response is ready or needs correction.
        """
        if state["validation_trace"] and state["validation_trace"].is_valid:
            return "END"
        return "RESEARCHER"
