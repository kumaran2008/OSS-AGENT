import re
from typing import List, Dict
from tools.search import CodeSearcher
from tools.filesystem import SafeFileSystem


class RelevanceEngine:
    """
    Finds files in the repo most likely relevant to an issue, using
    keyword search — not a full AST/semantic index, but enough to avoid
    sending the entire repo's context to every LLM call. Extracts
    candidate keywords from the issue title/body (error messages,
    quoted identifiers, function-like names) rather than requiring the
    caller to supply them manually.
    """

    def __init__(self, fs: SafeFileSystem):
        self.fs = fs
        self.searcher = CodeSearcher(fs)

    def extract_keywords(self, issue_title: str, issue_body: str) -> List[str]:
        text = f"{issue_title}\n{issue_body}"
        keywords = set()

        # Quoted strings/identifiers: `some_function`, "SomeClass", 'ERROR_CODE'
        for match in re.findall(r"[`'\"]([A-Za-z_][A-Za-z0-9_]{2,})[`'\"]", text):
            keywords.add(match)

        # CamelCase or snake_case tokens that look like real symbols, not prose
        for match in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{3,})\b", text):
            if "_" in match or (match[0].isupper() and any(c.islower() for c in match)):
                keywords.add(match)

        # Cap to avoid an excessive number of searches on a long issue body
        return list(keywords)[:10]

    def find_relevant_files(self, issue_title: str, issue_body: str, max_files: int = 5) -> List[str]:
        keywords = self.extract_keywords(issue_title, issue_body)
        if not keywords:
            return []

        matched: Dict[str, int] = {}  # file_path -> number of keyword hits, used to rank
        for kw in keywords:
            hits = self.searcher.search_symbol_or_text(kw, max_results=10)
            for hit in hits:
                file_path = hit["file"]
                if file_path.startswith(".git/"):
                    continue
                matched[file_path] = matched.get(file_path, 0) + 1

        ranked = sorted(matched.items(), key=lambda kv: kv[1], reverse=True)
        return [path for path, _ in ranked[:max_files]]

    def build_relevant_context(self, issue_title: str, issue_body: str, max_files: int = 5,
                                max_chars_per_file: int = 1500) -> str:
        """
        Returns a formatted context string containing the most relevant
        files' content, capped per-file to control prompt size. Empty
        string if nothing relevant was found (caller should fall back to
        generic README/doc context in that case).
        """
        relevant_files = self.find_relevant_files(issue_title, issue_body, max_files)
        if not relevant_files:
            return ""

        sections = []
        for file_path in relevant_files:
            try:
                content = self.fs.read_file(file_path)
            except Exception:
                continue
            truncated = content[:max_chars_per_file]
            suffix = "\n... (truncated)" if len(content) > max_chars_per_file else ""
            sections.append(f"--- Relevant file: {file_path} ---\n{truncated}{suffix}")

        if not sections:
            return ""

        return "\n\n=== Files most relevant to this issue ===\n" + "\n\n".join(sections) + "\n"
