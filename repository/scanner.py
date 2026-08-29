from typing import Dict
from tools.filesystem import SafeFileSystem


class LocalScanner:
    def __init__(self, fs: SafeFileSystem):
        self.fs = fs

    def get_core_docs(self) -> Dict[str, str]:
        docs = {}
        for t in ["README.md", "CONTRIBUTING.md", "setup.py", "pyproject.toml", "package.json"]:
            try:
                docs[t] = self.fs.read_file(t)[:3000]
            except Exception:
                continue
        return docs

    def scan_project_structure(self) -> Dict[str, str]:
        files = self.fs.list_files(".")
        top_level = sorted(set(f.split("/")[0] for f in files))
        return {"file_count": str(len(files)), "top_level_entries": ", ".join(top_level)}
