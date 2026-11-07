from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

print("[ORYN Cleanup]: Scanning repository workspace...")

# 1. Remove bulky reference PDFs from the workspace root if present
pdf_files = list(REPO_ROOT.glob("*.pdf"))
for pdf in pdf_files:
    try:
        pdf.unlink()
        print(f"  -> Removed reference PDF: {pdf.name}")
    except Exception as e:
        print(f"  -> Failed to remove {pdf.name}: {e}")

# 2. Clean up temporary cache or stray scratch scripts (keeping tools/verify_oryn_full.py & bridge_computer_suite.py)
allowed_tools = {"repo_connection_auditor.py", "verify_oryn_full.py", "bridge_computer_suite.py", "clean_repo.py"}
tools_dir = REPO_ROOT / "tools"
if tools_dir.exists():
    for f in tools_dir.glob("*.py"):
        if f.name not in allowed_tools:
            try:
                f.unlink()
                print(f"  -> Removed stray tool script: {f.name}")
            except Exception:
                pass

# 3. Ensure robust .gitignore rules for databases, audio buffers, and compiled artifacts
gitignore_path = REPO_ROOT / ".gitignore"
gitignore_content = """
# Python / Runtime Caches
__pycache__/
*.py[cod]
.pytest_cache/
*.so

# Local Databases & State
workspace/kernel_governance.db
workspace/kernel_governance.db-wal
workspace/kernel_governance.db-shm
workspace/.shadow_twins/
workspace/audio_buffers/
workspace/screen_capture.png
workspace/uidump.xml
workspace/oryn_*.csv
workspace/oryn_*.txt

# Secrets & Environment
.env
.env.*
!.env.example
"""

if gitignore_path.exists():
    existing = gitignore_path.read_text(encoding="utf-8")
    if "kernel_governance.db" not in existing:
        gitignore_path.write_text(existing + "\n" + gitignore_content, encoding="utf-8")
        print("  -> Updated .gitignore with local DB and runtime exclusions.")
else:
    gitignore_path.write_text(gitignore_content.strip() + "\n", encoding="utf-8")
    print("  -> Created .gitignore.")

print("[ORYN Cleanup]: Workspace sanitized successfully!")
