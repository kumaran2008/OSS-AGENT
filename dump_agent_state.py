import os
import ast
import json
from pathlib import Path

def inspect_project():
    root = Path(".").resolve()
    print("=" * 70)
    print("           OSS-AGENT WORKSPACE INVENTORY & STATE DUMP")
    print("=" * 70)

    # 1. Model Registry Status
    reg_path = root / "agent/pa_scaffolder/model_registry.json"
    if reg_path.exists():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            print("\n[+] MODEL REGISTRY (model_registry.json):")
            print(f"  • Room Bindings: {data.get('room_assignments')}")
            print(f"  • Task Bindings: {data.get('task_assignments')}")
            print(f"  • Configured Endpoints ({len(data.get('endpoints', {}))}): {list(data.get('endpoints', {}).keys())}")
        except Exception as e:
            print(f"  [!] Failed to parse model_registry.json: {e}")
    else:
        print("\n[!] model_registry.json NOT FOUND.")

    # 2. Source Files Scan
    scaffolder_dir = root / "agent/pa_scaffolder"
    if scaffolder_dir.exists():
        print("\n[+] CORE AGENT MODULES (agent/pa_scaffolder):")
        py_files = sorted(scaffolder_dir.glob("*.py"))
        for f in py_files:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            # Extract top-level AST classes and async functions
            classes = []
            functions = []
            try:
                tree = ast.parse("\n".join(lines), filename=f.name)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        classes.append(node.name)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions.append(node.name)
            except Exception:
                pass
            print(f"  • {f.name:<32} | {len(lines):>4} lines | Classes: {classes[:3]} | Funcs: {len(functions)}")

    # 3. Test Files Scan
    test_files = sorted(root.glob("test_*.py"))
    print(f"\n[+] BENCHMARKS & TEST SCRIPTS ({len(test_files)} files):")
    for tf in test_files:
        line_cnt = len(tf.read_text(encoding="utf-8", errors="replace").splitlines())
        print(f"  • {tf.name:<35} | {line_cnt:>4} lines")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    inspect_project()
