import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

IGNORED_DIRS: Set[str] = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".experience",
    ".adapters",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "eggs",
    ".tox",
}


class SymbolExtractor(ast.NodeVisitor):
    """Walks an AST and extracts function, class, and method signatures."""

    def __init__(self):
        self.entries: List[str] = []
        self._current_class: Optional[str] = None

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b))
            except Exception:
                pass
        bases_str = f"({', '.join(bases)})" if bases else ""
        self.entries.append(f"  class {node.name}{bases_str}:")
        prev_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record_func(node, is_async=True)

    def _record_func(self, node, is_async: bool = False):
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                try:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                except Exception:
                    pass
            args.append(arg_str)

        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")

        ret_str = ""
        if node.returns:
            try:
                ret_str = f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass

        prefix = "async def" if is_async else "def"
        sig = f"{prefix} {node.name}({', '.join(args)}){ret_str}: ..."

        if self._current_class:
            self.entries.append(f"    {sig}")
        else:
            self.entries.append(f"  {sig}")


class RepoMapGenerator:
    """
    Generates a token-compact symbol skeleton of the codebase.
    Enables 3B models to inspect cross-module classes, methods, and
    function signatures without exceeding small context windows.
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = (workspace_root or Path.cwd()).resolve()

    def _should_skip_dir(self, dir_path: Path) -> bool:
        return dir_path.name in IGNORED_DIRS or dir_path.name.startswith(".")

    def parse_file_symbols(self, file_path: Path) -> List[str]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return []

        extractor = SymbolExtractor()
        extractor.visit(tree)
        return extractor.entries

    def generate_map(self, max_chars: int = 4000) -> str:
        """
        Scans all Python files in the workspace and produces a compact
        AST skeleton string capped at max_chars (~1000 tokens).
        """
        lines = ["[CODEBASE SKELETON MAP]"]
        total_chars = 0

        for root, dirs, files in os.walk(self.workspace_root):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if not self._should_skip_dir(Path(root) / d)]

            rel_root = Path(root).relative_to(self.workspace_root)
            py_files = sorted([f for f in files if f.endswith(".py")])

            for py_file in py_files:
                file_path = Path(root) / py_file
                rel_path = (rel_root / py_file) if str(rel_root) != "." else Path(py_file)
                symbols = self.parse_file_symbols(file_path)

                if not symbols:
                    continue

                file_header = f"\n{rel_path}:"
                lines.append(file_header)
                total_chars += len(file_header)

                for sym in symbols:
                    if total_chars + len(sym) + 1 > max_chars:
                        lines.append("  ... [truncated: budget reached]")
                        return "\n".join(lines)
                    lines.append(sym)
                    total_chars += len(sym) + 1

        return "\n".join(lines)


if __name__ == "__main__":
    generator = RepoMapGenerator()
    repo_map = generator.generate_map()
    print(repo_map)
