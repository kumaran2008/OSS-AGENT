from pathlib import Path
from tools.filesystem import SafeFileSystem
from repository.scanner import LocalScanner
from repository.relevance import RelevanceEngine


class RepositoryContext:
    def __init__(self, workspace_path: Path):
        self.fs = SafeFileSystem(workspace_path)
        self.scanner = LocalScanner(self.fs)
        self.relevance = RelevanceEngine(self.fs)

    def assemble_context(self, issue_title: str = "", issue_body: str = "") -> str:
        docs = self.scanner.get_core_docs()
        structure = self.scanner.scan_project_structure()
        ctx = [f"=== Project structure ===\n{structure}\n"]
        for name, content in docs.items():
            ctx.append(f"=== File: {name} ===\n{content}\n")

        if issue_title or issue_body:
            relevant = self.relevance.build_relevant_context(issue_title, issue_body)
            if relevant:
                ctx.append(relevant)

        return "\n".join(ctx)
