import os
import sys
import yaml
import hashlib
import json
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DE L'AUDIT RÉSEAU (DO-326A)
# ──────────────────────────────────────────────────────────────────────────────

DOCKER_COMPOSE_PATH = "docker-compose.yml"
ALLOWED_EXPOSED_SERVICES = {
    "node-gateway": ["3000:3000"],
}
FORBIDDEN_SERVICES_WITH_PORTS = ["python-backend", "neo4j"]

def run_network_audit():
    """
    Vrifie la scurit du primtre réseau en analysant le docker-compose.yml.
    Garantit qu'aucun service critique (Python/Neo4j) n'expose de port sur l'hte.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    compose_file = os.path.join(root_dir, DOCKER_COMPOSE_PATH)
    
    print(f"[*] Starting Network Infrastructure Audit (S2) on: {compose_file}")
    
    if not os.path.exists(compose_file):
        print(f"[!] ERROR: {DOCKER_COMPOSE_PATH} not found!")
        sys.exit(1)
        
    try:
        with open(compose_file, "r") as f:
            compose_data = yaml.safe_load(f)
            # We also need the raw content for hashing
            f.seek(0)
            raw_content = f.read()
    except Exception as e:
        print(f"[!] ERROR: Failed to parse {DOCKER_COMPOSE_PATH}: {e}")
        sys.exit(1)

    services = compose_data.get("services", {})
    violations = []

    for service_name, config in services.items():
        ports = config.get("ports", [])
        
        # Rule 1: Forbidden services must NOT have 'ports'
        if service_name in FORBIDDEN_SERVICES_WITH_PORTS:
            if ports:
                violations.append(f"Service '{service_name}' violates isolation policy: found ports mapping {ports}")
        
        # Rule 2: Only node-gateway can expose 3000
        if service_name == "node-gateway":
            for p in ports:
                # Ports can be "3000:3000" (string) or a dict in some compose versions
                p_str = str(p)
                if "3000" not in p_str:
                    violations.append(f"Gateway service '{service_name}' has unexpected port mapping: {p_str}")
        elif service_name not in FORBIDDEN_SERVICES_WITH_PORTS:
            # Other services (if any)
            if ports:
                violations.append(f"Unrecognized service '{service_name}' is exposing ports {ports}")

    if violations:
        print("\n[!] INFRASTRUCTURE SECURITY BREACH DETECTED!")
        for v in violations:
            print(f"    - {v}")
        sys.exit(1)

    print("[+] NETWORK AUDIT SUCCESS: Isolation perimeter is intact.")
    generate_certified_report(root_dir, raw_content)

def generate_certified_report(root_dir, compose_content):
    """
    Gnre un rapport d'audit S2 avec hash SHA-256 du docker-compose.
    """
    report_dir = os.path.join(root_dir, "backend", "audit", "reports")
    timestamp = datetime.now().isoformat()
    
    # Calcul du hash du fichier audité
    compose_hash = hashlib.sha256(compose_content.encode()).hexdigest()
    
    report_data = {
        "status": "VALIDATED",
        "timestamp": timestamp,
        "scope": "Sprint 2 — Infrastructure & Network Isolation",
        "audited_file": DOCKER_COMPOSE_PATH,
        "audited_file_hash": compose_hash,
        "checks": [
            "Python Backend Isolation (No port mapping)",
            "Neo4j Isolation (No port mapping)",
            "Single Gateway Entry Point (Port 3000)"
        ]
    }
    
    # Calcul de la signature du rapport lui-même
    report_str = json.dumps(report_data, sort_keys=True)
    report_data["audit_signature"] = hashlib.sha256(report_str.encode()).hexdigest()
    
    report_file = os.path.join(report_dir, "s2_network_report.json")
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=4)
    
    print(f"[+] Certified report generated: {report_file}")
    print(f"    Docker-Compose Hash: {compose_hash}")

if __name__ == "__main__":
    run_network_audit()
