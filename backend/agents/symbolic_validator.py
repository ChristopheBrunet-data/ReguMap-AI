import re
from neo4j import Driver
from typing import List, Dict, Any, Tuple

from api_pkg.schemas import ValidationTrace

class SymbolicValidator:
    """
    Validateur Déterministe pour garantir la Robustesse Certifiable.
    L'approche stochastique (LLM) est strictement bridée par la logique symbolique Neo4j.
    """
    
    def __init__(self, driver: Driver):
        self.driver = driver
        # Hardened regex for EASA/FAA regulatory IDs (DO-178C/326A compliance)
        # Supports: AMC 20-27, CAT.IDE.A.190, Part-IS.AR.10, ORO.GEN.200, etc.
        self.id_pattern = re.compile(r'\b(?:AMC\d*|GM\d*|CS|Part-[A-Z]+|ORO|CAT|SPA|ADR|CM)(?:[\.\-\s][a-zA-Z0-9\-]+)+\b')

    def _extract_entities(self, assertion: str) -> List[str]:
        """Extrait les identifiants réglementaires (entités) de l'assertion du LLM."""
        return list(set(self.id_pattern.findall(assertion)))

    def validate_assertion(self, assertion: str) -> ValidationTrace:
        """
        Analyse l'assertion, génère/exécute une requête Cypher stricte,
        et retourne la preuve cryptographique.
        """
        claimed_ids = self._extract_entities(assertion)
        
        if not claimed_ids:
            # S'il n'y a aucune référence réglementaire, on ne peut pas garantir la traçabilité.
            # En aéronautique, une affirmation sans source est invalide.
            return ValidationTrace(
                is_valid=False,
                verified_nodes=[],
                missing_nodes=[],
                cryptographic_hashes={},
                error_message="ERR_NO_EVIDENCE: L'assertion ne contient aucune référence réglementaire traçable.",
                cypher_query_executed=None
            )

        # Génération d'une requête Cypher stricte pour vérifier l'existence
        cypher_query = """
        MATCH (n) WHERE n.node_id IN $node_ids
        RETURN n.node_id AS node_id, n.content_hash AS node_hash
        """
        
        found_map: Dict[str, str] = {}
        with self.driver.session() as session:
            records = session.run(cypher_query, node_ids=claimed_ids)
            for record in records:
                found_map[record["node_id"]] = record["node_hash"]
                
        verified_ids = list(found_map.keys())
        missing_ids = [cid for cid in claimed_ids if cid not in found_map]
        
        # Vérification booléenne stricte : 100% des entités citées DOIVENT exister en base.
        is_valid = len(missing_ids) == 0
        error_msg = None
        
        if not is_valid:
            error_msg = f"ERR_DATA_NOT_FOUND: Les références suivantes ont été hallucinées et n'existent pas dans la base de vérité: {missing_ids}"
            
        return ValidationTrace(
            is_valid=is_valid,
            verified_nodes=verified_ids,
            missing_nodes=missing_ids,
            cryptographic_hashes=found_map,
            error_message=error_msg,
            cypher_query_executed=cypher_query
        )
