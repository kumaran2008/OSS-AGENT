# repository/context.py
from pathlib import Path
from tools.filesystem import SafeFileSystem
from repository.scanner import LocalScanner

class RepositoryContext:
    def __init__(self, workspace_path: Path):
        self.fs = SafeFileSystem(workspace_path)
        self.scanner = LocalScanner(self.fs)

    def assemble_context(self) -> str:
        docs = self.scanner.get_core_docs()
        ctx = []
        for name, content in docs.items():
            ctx.append(f"=== File: {name} ===\n{content}\n")
        return "\n".join(ctx)
