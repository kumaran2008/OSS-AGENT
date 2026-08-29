# tools/search.py
import re
from pathlib import Path
from typing import List, Dict
from tools.filesystem import SafeFileSystem

class CodeSearcher:
    def __init__(self, fs: SafeFileSystem):
        self.fs = fs

    def search_symbol_or_text(self, query: str, max_results: int = 50) -> List[Dict[str, str]]:
        results = []
        files = self.fs.list_files(".")
        pattern = re.compile(re.escape(query), re.IGNORECASE)

        for file_path in files:
            if file_path.startswith(".git/"):
                continue
            try:
                content = self.fs.read_file(file_path)
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    if pattern.search(line):
                        results.append({
                            "file": file_path,
                            "line": str(idx),
                            "content": line.strip()
                        })
                        if len(results) >= max_results:
                            return results
            except Exception:
                continue
        return results
