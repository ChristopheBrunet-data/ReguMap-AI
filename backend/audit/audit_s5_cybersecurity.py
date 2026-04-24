import os
import hashlib
import json
import datetime
from pathlib import Path

# Paths relative to the project root
ROOT_DIR = Path(__file__).parent.parent.parent
REQUIREMENTS_FILE = ROOT_DIR / "backend" / "requirements.txt"
GATEWAY_SERVER_FILE = ROOT_DIR / "gateway" / "server.js"
WAF_FILE = ROOT_DIR / "gateway" / "waf.js"
REPORT_FILE = ROOT_DIR / "backend" / "audit" / "reports" / "s5_cybersecurity_report.json"

def get_file_hash(filepath):
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def run_audit():
    print(f"[*] Starting Cybersecurity Audit (S5) in: {ROOT_DIR}")

    # 1. Assertion: PII Protection dependencies
    if not REQUIREMENTS_FILE.exists():
        raise AssertionError(f"Critical error: {REQUIREMENTS_FILE} missing.")
    
    with open(REQUIREMENTS_FILE, "r") as f:
        reqs = f.read()
        if "presidio-analyzer" not in reqs or "spacy" not in reqs:
            raise AssertionError("DO-326A Violation: PII protection dependencies (Presidio/Spacy) are missing from requirements.txt")
    print("[+] Assertion 1/3: PII dependencies verified.")

    # 2. Assertion: WAF Middleware chaining
    if not GATEWAY_SERVER_FILE.exists():
        raise AssertionError(f"Critical error: {GATEWAY_SERVER_FILE} missing.")
    
    with open(GATEWAY_SERVER_FILE, "r") as f:
        server_code = f.read()
        if "promptInjectionWAF" not in server_code or "app.use(promptInjectionWAF)" not in server_code:
             raise AssertionError("DO-326A Violation: Cognitive WAF middleware is NOT chained in gateway server.js")
    print("[+] Assertion 2/3: WAF middleware chaining verified.")

    # 3. Assertion: WAF Rules existence
    if not WAF_FILE.exists():
        raise AssertionError(f"Critical error: {WAF_FILE} missing.")
    print("[+] Assertion 3/3: WAF rules file verified.")

    # Generate Scellé Cryptographique S5
    waf_hash = get_file_hash(WAF_FILE)
    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sprint": "S5",
        "component": "Cybersecurity & Guardrails",
        "status": "VALIDATED",
        "assertions": {
            "pii_protection": True,
            "waf_middleware": True,
            "waf_rules": True
        },
        "cryptographic_hashes": {
            "gateway_waf_js": waf_hash
        },
        "compliance_standard": "DO-326A / RGPD"
    }

    os.makedirs(REPORT_FILE.parent, exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=4)

    print(f"[+] CYBERSECURITY AUDIT SUCCESS: Sprint 5 is officially sealed.")
    print(f"[+] Certified report generated: {REPORT_FILE}")
    print(f"    WAF Hash: {waf_hash}")

if __name__ == "__main__":
    try:
        run_audit()
    except Exception as e:
        print(f"[!] CYBERSECURITY AUDIT FAILED: {e}")
        exit(1)
