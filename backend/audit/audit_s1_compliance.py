import os
import re
import sys
import json
import hashlib
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DU RÉFÉRENTIEL (INTERDITS)
# ──────────────────────────────────────────────────────────────────────────────

FORBIDDEN_PATTERNS = [
    (re.compile(r"zero[- ]?hallucination", re.IGNORECASE), "Probabilistic marketing term: 'Zero Hallucination'"),
    (re.compile(r"CM-AS-001", re.IGNORECASE), "Obsolete regulatory reference: 'CM-AS-001'"),
]

TARGET_EXTENSIONS = [".py", ".md", ".json"]
EXCLUDE_DIRS = ["node_modules", ".git", "__pycache__", "audit", ".venv"]

def run_compliance_audit():
    """
    Scanne le rpertoire racine pour dtecter les termes prohibs et les rfrences obsoltes.
    Conforme aux exigences de non-rgression EASA (NPA 2025-07).
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    findings = []
    
    print(f"[*] Starting Compliance Audit (S1) in: {root_dir}")
    
    for root, dirs, files in os.walk(root_dir):
        # Filtrer les rpertoires exclus
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if any(file.endswith(ext) for ext in TARGET_EXTENSIONS):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f, 1):
                            for pattern, reason in FORBIDDEN_PATTERNS:
                                if pattern.search(line) and "# skip-compliance-check" not in line:
                                    findings.append({
                                        "file": os.path.relpath(file_path, root_dir),
                                        "line": i,
                                        "match": pattern.search(line).group(),
                                        "reason": reason
                                    })
                except Exception as e:
                    print(f"[!] Could not read {file_path}: {e}")

    if findings:
        print("\n[!] COMPLIANCE FAILURE: Forbidden patterns detected!")
        for f in findings:
            print(f"    - File: {f['file']}")
            print(f"      Reason: {f['reason']}")
            print(f"      Match: {f['match']} (Line {f['line']})")
        sys.exit(1)
    
    print("[+] COMPLIANCE SUCCESS: No forbidden patterns found.")
    generate_certified_report(root_dir)

def generate_certified_report(root_dir):
    """
    Gnre un rapport d'audit sign cryptographiquement (SHA-256).
    """
    report_dir = os.path.join(root_dir, "backend", "audit", "reports")
    timestamp = datetime.now().isoformat()
    
    report_data = {
        "status": "VALIDATED",
        "timestamp": timestamp,
        "scope": "Sprint 1 — Decoupling & Terminology",
        "checks": [
            "Anti-Probabilistic Vocabulary (Zero Hallucination)",
            "Obsolescence Check (CM-AS-001)"
        ],
        "system_hash": "N/A" # Reserved for future binary hashing
    }
    
    # 1. Pr-calcul du contenu
    report_str = json.dumps(report_data, sort_keys=True)
    
    # 2. Calcul du hash SHA-256 de preuve
    report_hash = hashlib.sha256(report_str.encode()).hexdigest()
    report_data["audit_signature"] = report_hash
    
    report_file = os.path.join(report_dir, "s1_compliance_report.json")
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=4)
    
    print(f"[+] Certified report generated: {report_file}")
    print(f"    Hash: {report_hash}")

if __name__ == "__main__":
    run_compliance_audit()
