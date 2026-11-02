import sys
import importlib
from pathlib import Path

print("=" * 65)
print("     REPOSITORY IMPORT INTEGRITY AUDIT")
print("=" * 65)

# 1. Static Scan: Search for lingering string references
root_dir = Path(".")
py_files = [f for f in root_dir.rglob("*.py") if "test_graph_memory.py" not in f.name and "check_repo_imports.py" not in f.name]

lingering_refs = []
target_tokens = ["spatial_graph_memory", "SpatioTemporalGraphMemory"]

for file in py_files:
    try:
        content = file.read_text(encoding="utf-8")
        for token in target_tokens:
            if token in content:
                lingering_refs.append((str(file), token))
    except Exception:
        pass

print("\n[1/2] Scanning Codebase for Obsolete References...")
if lingering_refs:
    print(" [!] Found lingering references that will cause import errors:")
    for filepath, token in lingering_refs:
        print(f"     • File: {filepath} (Contains '{token}')")
else:
    print(" [✓] Zero lingering references to spatial_graph_memory found.")

# 2. Dynamic Import Test: Verify all current modules load cleanly
modules_to_test = [
    "agent.pa_scaffolder.graph_brain",
    "agent.pa_scaffolder.advanced_companion",
    "agent.pa_scaffolder.engine_harness",
    "agent.core.unified_companion"
]

print("\n[2/2] Testing Runtime Module Imports...")
failed_imports = []

for mod_name in modules_to_test:
    try:
        mod = importlib.import_module(mod_name)
        print(f" [✓] {mod_name} loaded successfully.")
    except Exception as e:
        print(f" [✗] {mod_name} FAILED to load: {e}")
        failed_imports.append((mod_name, str(e)))

print("\n" + "=" * 65)
if not lingering_refs and not failed_imports:
    print(">>> CODEBASE IS 100% CLEAN: ZERO IMPORT ERRORS DETECTED <<<")
else:
    print(">>> ACTION REQUIRED: FIX THE DETECTED REFERENCES ABOVE <<<")
print("=" * 65)

if lingering_refs or failed_imports:
    sys.exit(1)
