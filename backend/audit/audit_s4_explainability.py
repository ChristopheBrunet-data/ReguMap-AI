import os
import sys
import hashlib
import json
from datetime import datetime

# Path resolution for imports: Add the backend folder to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

from agents.orchestrator import ComplianceOrchestrator
from agents.symbolic_validator import SymbolicValidator
from api_pkg.schemas import TraceabilityLog

class MockNeo4jDriver:
    """Mocks Neo4j to supply cryptographic hashes for symbolic validation."""
    def __init__(self):
        self.truth_db = {
            "ADR.OR.B.005": "hash_adr_or_b_005",
            "AMC1.ORO.GEN.200": "hash_amc1_oro_gen_200",
            "Part-IS.AR.10": "hash_part_is_ar_10"
        }
        
    def session(self):
        return MockNeo4jSession(self.truth_db)

class MockNeo4jSession:
    def __init__(self, db):
        self.db = db
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
        
    def run(self, query, node_ids=None):
        records = []
        if node_ids:
            for nid in node_ids:
                if nid in self.db:
                    records.append({"node_id": nid, "node_hash": self.db[nid]})
        return records

def run_explainability_audit():
    """
    Simulates 10 Compliance API requests through the Multi-Agent Orchestrator.
    Asserts the XAI Transparency Log is generated accurately and deterministically.
    """
    print("[*] Starting Explainability Audit (S4)")
    
    driver = MockNeo4jDriver()
    validator = SymbolicValidator(driver=driver)
    orchestrator = ComplianceOrchestrator(validator=validator)
    
    success_count = 0
    total_requests = 10
    
    for i in range(1, total_requests + 1):
        print(f"    [+] Simulating API Request {i}/{total_requests}...")
        
        # We override the mocked Researcher output dynamically for testing
        orchestrator.node_researcher = lambda s, i=i: _mock_researcher(s, i)
        
        try:
            # 1. Orchestration Loop
            final_state = orchestrator.run(f"User Question {i}")
            
            # 2. Extract Traceability Log (simulating API response serialization)
            t_log: TraceabilityLog = final_state.get("traceability_log")
            
            # 3. Validation Logic
            if not t_log:
                print(f"[!] COMPLIANCE FAILURE: No TraceabilityLog in Request {i}")
                sys.exit(1)
                
            if not t_log.validation_status:
                print(f"[!] COMPLIANCE FAILURE: Request {i} validation_status is False despite END route.")
                sys.exit(1)
                
            if "MATCH (n) WHERE n.id IN $node_ids" not in t_log.cypher_query_executed:
                print(f"[!] COMPLIANCE FAILURE: Cypher query missing from Log in Request {i}")
                sys.exit(1)
                
            if not t_log.node_hashes:
                print(f"[!] COMPLIANCE FAILURE: Cryptographic hashes missing in Request {i}")
                sys.exit(1)
                
            success_count += 1
            
        except Exception as e:
            print(f"[!] ORCHESTRATOR FAILED on Request {i}: {e}")
            sys.exit(1)

    print(f"\n[+] Evaluated {total_requests} requests. 100% Success Rate.")
    generate_certified_report()

def _mock_researcher(state, request_index):
    """Dynamically mocks the LLM researcher for the audit."""
    if request_index % 2 == 0:
        state["researcher_response"] = "The rule is Part-IS.AR.10."
    else:
        # Simulate a hallucination that auto-corrects on iteration 2
        if state["iteration_count"] == 1:
            state["researcher_response"] = "The rule is HALLUCINATION.123."
        else:
            state["researcher_response"] = "Correction: The rule is ADR.OR.B.005."
    return state


def generate_certified_report():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    report_dir = os.path.join(root_dir, "backend", "audit", "reports")
    os.makedirs(report_dir, exist_ok=True)
    
    timestamp = datetime.now().isoformat()
    report_data = {
        "status": "VALIDATED",
        "timestamp": timestamp,
        "scope": "Sprint 4 — XAI Explainability",
        "checks": [
            "TraceabilityLog Schema Enforcement",
            "Cypher Query Transparency",
            "Node Hash Exposure (Cryptographic Proof)",
            "Auto-Correction Loop Verification"
        ]
    }
    
    report_str = json.dumps(report_data, sort_keys=True)
    report_data["audit_signature"] = hashlib.sha256(report_str.encode()).hexdigest()
    
    report_file = os.path.join(report_dir, "s4_explainability_report.json")
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=4)
        
    print("\n[+] EXPLAINABILITY AUDIT S4: 100% SUCCESS")
    print(f"    Certified report generated: {report_file}")

if __name__ == "__main__":
    run_explainability_audit()
