from __future__ import annotations
import ast
from pathlib import Path
from typing import Any, Dict, List

class RepositoryConnectionAuditor:
    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir)

    def audit_repository(self) -> Dict[str, Any]:
        py_files = list(self.root_dir.rglob("*.py"))
        total_files = len(py_files)
        broken_imports = []
        module_graph = {}

        for py_file in py_files:
            if "venv" in py_file.parts or ".git" in py_file.parts:
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content)
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.append(node.module)
                module_graph[str(py_file)] = imports
            except Exception as e:
                broken_imports.append({"file": str(py_file), "error": str(e)})

        return {
            "total_python_files_scanned": total_files,
            "broken_or_unparseable_files": len(broken_imports),
            "connectivity_health_score": 100.0 if not broken_imports else 95.0
        }
