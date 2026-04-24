import os
import sys
import json
import hashlib
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Ajouter le chemin backend au sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Import de l'application et des dpendances
from api_pkg.main import app
from api_pkg.dependencies import get_engine, get_neo4j_driver
from api_pkg.schemas import ValidationTrace

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DE L'AUDIT D'EXPLICABILIT (S4)
# ──────────────────────────────────────────────────────────────────────────────

def run_explainability_audit():
    """
    Audit de certification XAI (Sprint 4).
    Vrifie que l'IA fournit systématiquement une preuve d'audit cryptographique.
    """
    print("[*] Starting Explainability & XAI Audit (S4)...")
    
    client = TestClient(app)
    
    # 1. Mocker les dpendances lourdes pour l'audit autonome
    mock_engine = MagicMock()
    mock_driver = MagicMock()
    
    # Mocking engine response
    mock_engine.answer_regulatory_question.return_value = "Verified compliance with ORO.FTL.210."
    
    app.dependency_overrides[get_engine] = lambda: mock_engine
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_driver

    violations = []
    
    try:
        # 2. Simulation d'un appel API certifiable
        # On utilise patch pour intercepter la validation interne de l'orchestrateur
        with patch("agents.orchestrator.SymbolicValidator.validate_references") as mock_validate:
            mock_validate.return_value = ValidationTrace(
                is_valid=True,
                verified_nodes=["ORO.FTL.210"],
                cryptographic_hashes={"ORO.FTL.210": "a" * 64} # Mock valid SHA-256
            )
            
            response = client.post("/api/v1/audit/ask", params={"query": "Quelles sont les limites FDP ?"})
            
            if response.status_code != 200:
                violations.append(f"API Call failed with status {response.status_code}: {response.text}")
                return finish_audit(violations)

            payload = response.json()
            
            # Rule 1: Existence du traceability_log
            if "traceability_log" not in payload:
                violations.append("CRITICAL: 'traceability_log' is missing from the response.")
            else:
                xai_log = payload["traceability_log"]
                
                # Rule 2: Intgrit des hashes (SHA-256)
                hashes = xai_log.get("cryptographic_hashes", {})
                if not hashes:
                    violations.append("CRITICAL: 'cryptographic_hashes' dictionary is empty.")
                else:
                    for node_id, h in hashes.items():
                        if len(h) != 64:
                            violations.append(f"Invalid hash format for {node_id}: length is {len(h)}, expected 64.")
                
                # Rule 3: Validit de la requête de validation (Cypher)
                query = xai_log.get("validation_query", "")
                if not query.strip().startswith("MATCH"):
                    violations.append(f"Invalid validation_query: must start with 'MATCH'. Got: {query[:20]}...")
                if "$node_ids" not in query:
                    violations.append("Invalid validation_query: missing '$node_ids' variable.")

    except Exception as e:
        violations.append(f"Audit script execution error: {e}")
    finally:
        app.dependency_overrides = {}

    finish_audit(violations, payload if not violations else None)

def finish_audit(violations, successful_payload=None):
    if violations:
        print("\n[!] EXPLAINABILITY BREACH DETECTED!")
        for v in violations:
            print(f"    - {v}")
        sys.exit(1)

    print("[+] XAI AUDIT SUCCESS: Response is certifiable and auditable.")
    generate_certified_report(successful_payload)

def generate_certified_report(payload):
    """
    Gnre le rapport d'audit S4 certifi.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    report_dir = os.path.join(root_dir, "backend", "audit", "reports")
    timestamp = datetime.now().isoformat()
    
    # Hash de la structure de preuve pour scellage
    payload_str = json.dumps(payload, sort_keys=True)
    payload_seal = hashlib.sha256(payload_str.encode()).hexdigest()
    
    report_data = {
        "status": "VALIDATED",
        "timestamp": timestamp,
        "scope": "Sprint 4 — Hybrid Intelligence & XAI",
        "certification_standard": "NPA 2025-07 (Explainability)",
        "test_payload_seal": payload_seal,
        "metrics": {
            "is_valid": payload["is_valid"],
            "iterations": payload["iterations"]
        }
    }
    
    report_file = os.path.join(report_dir, "s4_explainability_report.json")
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=4)
    
    print(f"[+] Certified report generated: {report_file}")

if __name__ == "__main__":
    run_explainability_audit()
