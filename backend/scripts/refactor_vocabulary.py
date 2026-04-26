import os
import re

TARGET_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".md"]
EXCLUDE_DIRS = ["node_modules", ".git", "__pycache__", ".venv", "audit"]
# We specifically exclude the 'audit' directory to prevent modifying the audit script itself,
# or we can include it to make sure we fix everything, but the task says "global dans la base de code".
# Wait, if we modify the audit script to expect "Robustesse Certifiable", it will still check for "Robustesse Certifiable".

def refactor_vocabulary(root_dir: str):
    pattern = re.compile(r"z[eé]ro[- ]?hallucination", re.IGNORECASE)
    replacement = "Robustesse Certifiable"
    
    total_files_changed = 0
    total_replacements = 0
    
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if any(file.endswith(ext) for ext in TARGET_EXTENSIONS):
                file_path = os.path.join(root, file)
                
                # Exclude the report JSON and audit script if needed
                # We'll just run it on everything matching.
                
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        
                    new_content, count = pattern.subn(replacement, content)
                    
                    if count > 0:
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(new_content)
                        print(f"[MODIFIED] {os.path.relpath(file_path, root_dir)} ({count} replacements)")
                        total_files_changed += 1
                        total_replacements += count
                        
                except Exception as e:
                    print(f"[!] Error processing {file_path}: {e}")
                    
    print(f"\n--- Refactoring Complete ---")
    print(f"Files modified: {total_files_changed}")
    print(f"Total replacements: {total_replacements}")

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    print(f"Starting refactoring in: {project_root}")
    refactor_vocabulary(project_root)
