import os
import sys
import hashlib
import json
from datetime import datetime

# Importer les composants du pipeline
# On ajoute le chemin backend au sys.path si ncessaire
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from ingestion.easa_parser import parse_easa_xml

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DE L'AUDIT PIPELINE (S3)
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_EASA_PATH = "sample_easa.xml"
# Hash d'or (Golden Hash) pour ORO.FTL.210 garantissant l'intgrit du parseur
GOLDEN_HASH_REFERENCE = "5ef9e7a53706220698dd09f0b9361662ffa5c8fe3cebac3018d588941542513a"
GOLDEN_NODE_ID = "ORO.FTL.210"

def run_pipeline_audit():
    """
    Vrifie l'intgrit du pipeline d'ingestion (E2E).
    Assure que le parsing DOM et le hachage sont déterministes et conformes.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sample_file = os.path.join(root_dir, "backend", SAMPLE_EASA_PATH)
    
    print(f"[*] Starting Data Pipeline Audit (S3) on: {sample_file}")
    
    if not os.path.exists(sample_file):
        print(f"[!] ERROR: {sample_file} not found!")
        sys.exit(1)
        
    try:
        nodes = parse_easa_xml(sample_file)
    except Exception as e:
        print(f"[!] ERROR: Pipeline execution failed: {e}")
        sys.exit(1)

    violations = []
    golden_node_found = False

    for node in nodes:
        # Rule 1: Valid node_id
        if not node.node_id or len(node.node_id) < 3:
            violations.append(f"Invalid node_id detected: {node.node_id}")
            
        # Rule 2: Valid content_hash (SHA-256 length = 64)
        if not node.content_hash or len(node.content_hash) != 64:
            violations.append(f"Invalid content_hash for {node.node_id}: {node.content_hash}")
            
        # Rule 3: Golden Hash verification
        if node.node_id == GOLDEN_NODE_ID:
            golden_node_found = True
            if node.content_hash != GOLDEN_HASH_REFERENCE:
                violations.append(
                    f"GOLDEN HASH DIVERGENCE on {GOLDEN_NODE_ID}!\n"
                    f"    Expected: {GOLDEN_HASH_REFERENCE}\n"
                    f"    Got     : {node.content_hash}\n"
                    f"    (The parser logic or content reading might have changed silently)"
                )

    if not golden_node_found:
        violations.append(f"Reference node {GOLDEN_NODE_ID} not found in parsed data.")

    if violations:
        print("\n[!] PIPELINE INTEGRITY BREACH DETECTED!")
        for v in violations:
            print(f"    - {v}")
        sys.exit(1)

    print(f"[+] PIPELINE AUDIT SUCCESS: {len(nodes)} nodes validated.")
    generate_certified_report(root_dir, len(nodes))

def generate_certified_report(root_dir, node_count):
    """
    Gnre un rapport d'audit S3 certifi.
    """
    report_dir = os.path.join(root_dir, "backend", "audit", "reports")
    timestamp = datetime.now().isoformat()
    
    # Hash du script d'audit lui-mme pour traabilit
    with open(__file__, "rb") as f:
        script_hash = hashlib.sha256(f.read()).hexdigest()
    
    report_data = {
        "status": "VALIDATED",
        "timestamp": timestamp,
        "scope": "Sprint 3 — Data Pipeline & DOM Integrity",
        "nodes_processed": node_count,
        "golden_check": {
            "node_id": GOLDEN_NODE_ID,
            "status": "MATCH"
        },
        "audit_script_hash": script_hash
    }
    
    # Signature du rapport
    report_str = json.dumps(report_data, sort_keys=True)
    report_data["audit_signature"] = hashlib.sha256(report_str.encode()).hexdigest()
    
    report_file = os.path.join(report_dir, "s3_pipeline_report.json")
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=4)
    
    print(f"[+] Certified report generated: {report_file}")

if __name__ == "__main__":
    run_pipeline_audit()
