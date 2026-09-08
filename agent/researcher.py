import ast
import os
from pathlib import Path
from typing import Dict, Any, List
from tools.system_info import get_system_capabilities
from tools.multi_lang_ast import detect_language, extract_functions

class RepositoryResearchAgent:
    """
    Scans the repository to identify code architecture gaps, missing tests,
    bug reports, and feature enhancement opportunities. Adapts depth based on
    hardware specs.
    """

    def __init__(self, repo_dir: str = "."):
        self.repo_dir = str(repo_dir)
        self.specs = get_system_capabilities()

    def analyze_repository(self) -> Dict[str, Any]:
        """Performs structural AST & documentation scanning."""
        is_high_spec = self.specs["can_run_local_llama"]
        scan_mode = "Deep Repository Research" if is_high_spec else "Lightweight AST Research"
        
        print(f"\n=== [Research Agent] Running {scan_mode} ===")
        
        py_files = []
        other_lang_files = []
        for root, _, files in os.walk(self.repo_dir):
            if "venv" in root or ".git" in root or "__pycache__" in root or "node_modules" in root or "build" in root:
                continue
            for file in files:
                full_path = os.path.join(root, file)
                if file.endswith(".py"):
                    py_files.append(full_path)
                elif detect_language(Path(full_path)):
                    other_lang_files.append(full_path)

        unhandled_functions = []
        missing_tests = []

        # Analyze up to 10 files for low-spec (e.g. Termux), unlimited for high-spec.
        # Applies the same cap to both Python and other-language files, split
        # proportionally so a repo isn't entirely one or the other.
        max_py_files = len(py_files) if is_high_spec else min(10, len(py_files))
        max_other_files = len(other_lang_files) if is_high_spec else min(10, len(other_lang_files))

        for filepath in py_files[:max_py_files]:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    node = ast.parse(f.read(), filename=filepath)

                for item in ast.walk(node):
                    if isinstance(item, ast.FunctionDef):
                        if not ast.get_docstring(item):
                            unhandled_functions.append(f"{os.path.basename(filepath)} :: {item.name}()")
            except Exception:
                pass

        for filepath in other_lang_files[:max_other_files]:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                functions = extract_functions(Path(filepath), content)
                for fn in functions:
                    if not fn["has_doc"]:
                        unhandled_functions.append(f"{os.path.basename(filepath)} :: {fn['name']}() (line {fn['line']})")
            except Exception:
                pass

        all_scanned_files = py_files + other_lang_files
        has_tests = any("test" in f.lower() for f in all_scanned_files)
        if not has_tests and all_scanned_files:
            missing_tests.append("No dedicated test suite/files detected in project.")

        suggestions = []
        if unhandled_functions:
            suggestions.append(f"Add docstrings and error checks to {len(unhandled_functions)} undocumented functions.")
        if missing_tests:
            suggestions.append("Generate baseline unit tests to enable regression safety.")
        if is_high_spec:
            suggestions.append("Refactor module imports to use AST symbol mapping instead of regex searching.")

        if not suggestions:
            suggestions.append("Repository structure looks clean! No critical architectural gaps found.")

        return {
            "mode": scan_mode,
            "py_files_scanned": len(py_files[:max_py_files]),
            "other_files_scanned": len(other_lang_files[:max_other_files]),
            "unhandled_functions": unhandled_functions[:5],
            }
    def present_proposals(self) -> bool:
        """Displays proposed enhancements to user and returns True if approved."""
        analysis = self.analyze_repository()
        
        total_scanned = analysis['py_files_scanned'] + analysis.get('other_files_scanned', 0)
        print(f"\n--- [Research Report] Scanned {total_scanned} files "
              f"({analysis['py_files_scanned']} Python, {analysis.get('other_files_scanned', 0)} other languages) ---")
        for idx, sug in enumerate(analysis["suggestions"], 1):
            print(f"  {idx}. {sug}")
            
        print("--------------------------------------------------")
        try:
            confirm = input("\nDo you approve allocating sub-agents to implement these features/fixes? [y/N]: ").strip().lower()
            return confirm == "y"
        except EOFError:
            return False
