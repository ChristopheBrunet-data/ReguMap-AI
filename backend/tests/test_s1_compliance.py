import os
import sys

# Append parent dir so we can import the audit module
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)

from audit.audit_s1_compliance import FORBIDDEN_PATTERNS, TARGET_EXTENSIONS, EXCLUDE_DIRS

def test_s1_vocabulary_and_references():
    """
    Scans the repository to ensure that NO forbidden patterns are found.
    Fails if prohibited term or obsolete refs are found outside of skipped lines.
    """
    root_dir = os.path.abspath(os.path.join(backend_dir, ".."))
    findings = []
    
    for root, dirs, files in os.walk(root_dir):
        # Filter excluded directories
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
                    # Ignore unreadable files
                    pass
                    
    assert len(findings) == 0, f"Compliance failure! Found forbidden patterns: {findings}"
