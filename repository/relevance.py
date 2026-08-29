# repository/relevance.py
from typing import List
from tools.search import CodeSearcher

class RelevanceEngine:
    def __init__(self, searcher: CodeSearcher):
        self.searcher = searcher

    def find_relevant_files(self, keywords: List[str]) -> List[str]:
        matched_files = set()
        for kw in keywords:
            if not kw.strip():
                continue
            hits = self.searcher.search_symbol_or_text(kw, max_results=10)
            for h in hits:
                matched_files.add(h["file"])
        return list(matched_files)
