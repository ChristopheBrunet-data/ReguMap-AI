from neo4j import Driver
from typing import List, Set
from api_pkg.schemas import ValidationTrace
from graph.query_engine import verify_nodes_exist

class SymbolicValidator:
    """
    Deterministic validator to prevent LLM hallucinations.
    Ensures every regulatory citation is cross-checked against the Neo4j Graph.
    """
    
    def __init__(self, driver: Driver):
        self.driver = driver

    def validate_references(self, claimed_ids: List[str]) -> ValidationTrace:
        """
        Cross-references claimed IDs with the Graph.
        A response is ONLY valid if 100% of the claimed IDs exist in the database.
        """
        if not claimed_ids:
            return ValidationTrace(is_valid=True)

        # Deduplicate claimed IDs
        unique_claims = list(set(claimed_ids))
        
        # Query Neo4j for ground truth
        found_map = verify_nodes_exist(self.driver, unique_claims)
        
        verified_ids = list(found_map.keys())
        missing_ids = [cid for cid in unique_claims if cid not in found_map]
        
        is_valid = len(missing_ids) == 0
        error_msg = None
        
        if not is_valid:
            error_msg = f"Hallucination Detected: The following references do not exist in the regulatory database: {missing_ids}"
            
        return ValidationTrace(
            is_valid=is_valid,
            verified_nodes=verified_ids,
            missing_nodes=missing_ids,
            cryptographic_hashes=found_map,
            error_message=error_msg
        )
