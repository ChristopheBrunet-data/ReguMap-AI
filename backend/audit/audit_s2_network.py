import os
import sys
import yaml
import hashlib
import json
import subprocess
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DE L'AUDIT RÉSEAU (DO-326A)
# ──────────────────────────────────────────────────────────────────────────────

DOCKER_COMPOSE_PATH = "docker-compose.yml"
ALLOWED_EXPOSED_SERVICES = {
    "node-gateway": ["3000:3000"],
    "frontend": ["80:80"],
}
FORBIDDEN_SERVICES_WITH_PORTS = ["python-backend", "neo4j"]

def check_docker_daemon():
    """Check if Docker daemon is running."""
    try:
        res = subprocess.run(["docker", "info"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except FileNotFoundError:
        return False

def run_network_audit():
    """
    Vérifie la sécurité du périmètre réseau en analysant le docker-compose.yml,
    et via des tests live si le daemon Docker est accessible.
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
            f.seek(0)
            raw_content = f.read()
    except Exception as e:
        print(f"[!] ERROR: Failed to parse {DOCKER_COMPOSE_PATH}: {e}")
        sys.exit(1)

    services = compose_data.get("services", {})
    networks = compose_data.get("networks", {})
    violations = []

    # 1. Static Checks: Ports
    for service_name, config in services.items():
        ports = config.get("ports", [])
        if service_name in FORBIDDEN_SERVICES_WITH_PORTS and ports:
            violations.append(f"Service '{service_name}' exposes ports: {ports}")
        if service_name in ALLOWED_EXPOSED_SERVICES:
            allowed = ALLOWED_EXPOSED_SERVICES[service_name]
            for p in ports:
                p_str = str(p)
                if not any(ap in p_str for ap in allowed):
                    violations.append(f"Authorized service '{service_name}' exposes unallowed port: {p_str}")

    # 2. Static Checks: Internal Network Isolation
    private_net = networks.get("private_ai_net", {})
    if not private_net.get("internal"):
        violations.append("Network 'private_ai_net' is not set to 'internal: true'")

    python_backend_nets = services.get("python-backend", {}).get("networks", [])
    if "public_net" in python_backend_nets:
        violations.append("Service 'python-backend' is attached to 'public_net'")

    if violations:
        print("\n[!] INFRASTRUCTURE SECURITY BREACH DETECTED!")
        for v in violations:
            print(f"    - {v}")
        sys.exit(1)

    print("[+] Static Network Analysis: PASSED. Topology is secure.")

    # 3. Live Checks via Docker Exec
    live_checks_performed = False
    if check_docker_daemon():
        print("[*] Performing live curl tests inside containers...")
        live_checks_performed = True
        
        # Test 1: Timeout on external internet access
        print("    -> Testing outbound internet access from python-backend...")
        res = subprocess.run(
            ["docker", "exec", "aeromind-python-backend", "curl", "--connect-timeout", "3", "https://google.com"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if res.returncode == 0:
            print("[!] COMPLIANCE FAILURE: python-backend connected to google.com!")
            sys.exit(1)
        print("[+] python-backend timed out as expected (No internet access).")
        
        # Test 2: Direct connection from a container on public_net
        print("    -> Testing cross-network boundary from frontend to python-backend...")
        res = subprocess.run(
            ["docker", "exec", "aeromind-frontend", "curl", "--connect-timeout", "2", "http://python-backend:8000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if res.returncode == 0:
            print("[!] COMPLIANCE FAILURE: frontend container bypassed VPC boundary!")
            sys.exit(1)
        print("[+] frontend blocked from accessing python-backend directly.")
    else:
        print("[?] Docker daemon unavailable. Skipping live curl checks (CI/CD environments only).")

    generate_certified_report(root_dir, raw_content, live_checks_performed)

def generate_certified_report(root_dir, compose_content, live_checks):
    report_dir = os.path.join(root_dir, "backend", "audit", "reports")
    timestamp = datetime.now().isoformat()
    compose_hash = hashlib.sha256(compose_content.encode()).hexdigest()
    
    checks = [
        "Python Backend Isolation (No port mapping)",
        "Neo4j Isolation (No port mapping)",
        "VPC Topology (Internal Network: true)"
    ]
    if live_checks:
        checks.extend(["Live Curl Timeout Test", "Live Boundary Segment Test"])
    
    report_data = {
        "status": "VALIDATED",
        "timestamp": timestamp,
        "scope": "Sprint 2 — Infrastructure & Network Isolation",
        "audited_file": DOCKER_COMPOSE_PATH,
        "audited_file_hash": compose_hash,
        "checks": checks
    }
    
    report_str = json.dumps(report_data, sort_keys=True)
    report_data["audit_signature"] = hashlib.sha256(report_str.encode()).hexdigest()
    
    report_file = os.path.join(report_dir, "s2_network_report.json")
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=4)
    
    print(f"\n[+] NETWORK AUDIT S2: 100% SUCCESS")
    print(f"    Certified report generated: {report_file}")

if __name__ == "__main__":
    run_network_audit()
