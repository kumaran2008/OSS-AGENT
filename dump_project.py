import os
from pathlib import Path

IGNORE_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "test_pa_env", "workspace"}
ALLOWED_EXTS = {".py", ".json", ".md", ".sh", ".toml", ".yaml", ".yml"}

output_file = Path("project_dump.txt")
root_dir = Path(".")

with open(output_file, "w", encoding="utf-8") as out:
    out.write("=== PROJECT FILE TREE ===\n")
    for path in sorted(root_dir.rglob("*")):
        if any(ignored in path.parts for ignored in IGNORE_DIRS):
            continue
        if path.is_file() and path.suffix in ALLOWED_EXTS and path.name != "project_dump.txt":
            out.write(f"{path}\n")
    
    out.write("\n" + "=" * 60 + "\n")
    out.write("=== FILE CONTENTS ===\n")
    out.write("=" * 60 + "\n\n")
    
    for path in sorted(root_dir.rglob("*")):
        if any(ignored in path.parts for ignored in IGNORE_DIRS):
            continue
        if path.is_file() and path.suffix in ALLOWED_EXTS and path.name != "project_dump.txt":
            out.write(f"--- START FILE: {path} ---\n")
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"Error reading file: {e}\n")
            out.write(f"\n--- END FILE: {path} ---\n\n")

print(f"[✓] Complete project dump generated: {output_file.resolve()}")
print(f"[✓] File size: {output_file.stat().st_size / 1024:.2f} KB")
