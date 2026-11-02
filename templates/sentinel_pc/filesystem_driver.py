import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

RESTRICTED_DIRECTORIES = {".ssh", ".gnupg", "/etc/shadow", "/dev"}


class FilesystemDriver:
    """Manages file indexing, reading, writing, and directory searching."""

    def __init__(self, root_path: Optional[str] = None):
        self.root_path = Path(root_path or Path.home()).resolve()

    def _is_restricted(self, target: Path) -> bool:
        resolved = str(target.resolve())
        return any(blocked in resolved for blocked in RESTRICTED_DIRECTORIES)

    def read_file(self, file_path: str, max_bytes: int = 100_000) -> Dict[str, Any]:
        target = (self.root_path / file_path).resolve()
        if self._is_restricted(target):
            return {"success": False, "error": "Access denied: Restricted system path."}
        if not target.exists() or not target.is_file():
            return {"success": False, "error": f"File does not exist: {file_path}"}

        try:
            content = target.read_text(encoding="utf-8", errors="replace")[:max_bytes]
            return {"success": True, "content": content, "truncated": len(content) >= max_bytes}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write_file(self, file_path: str, content: str) -> Dict[str, Any]:
        target = (self.root_path / file_path).resolve()
        if self._is_restricted(target):
            return {"success": False, "error": "Access denied: Restricted system path."}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(target), "bytes_written": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_files(self, pattern: str, root_subpath: str = "", max_results: int = 25) -> List[str]:
        search_root = (self.root_path / root_subpath).resolve()
        matches = []
        for root, dirs, files in os.walk(search_root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in RESTRICTED_DIRECTORIES]
            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    rel = Path(root, filename).relative_to(self.root_path)
                    matches.append(str(rel))
                    if len(matches) >= max_results:
                        return matches
        return matches
