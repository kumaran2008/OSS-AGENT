# tools/filesystem.py
import os
from pathlib import Path
from typing import List

class SafeFileSystem:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def _validate_path(self, relative_or_absolute_path: str) -> Path:
        target_path = (self.workspace_root / relative_or_absolute_path).resolve()
        if not str(target_path).startswith(str(self.workspace_root)):
            raise PermissionError(f"Access denied: Path '{target_path}' escapes workspace directory.")
        return target_path

    def read_file(self, path: str) -> str:
        safe_path = self._validate_path(path)
        if not safe_path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def write_file(self, path: str, content: str) -> None:
        safe_path = self._validate_path(path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

    def list_files(self, relative_dir: str = ".") -> List[str]:
        safe_path = self._validate_path(relative_dir)
        results = []
        for root, _, files in os.walk(safe_path):
            for file in files:
                full = Path(root) / file
                rel = full.relative_to(self.workspace_root)
                results.append(str(rel))
        return results
