import os
import sys
import json
import re
import math
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

try:
    from agent.hardware.runtime_adapter import detect_hardware_tier, RuntimeTier
except ImportError:
    class RuntimeTier:
        LOW_SPEC_MOBILE = "low_spec_mobile"
        MID_SPEC = "mid_spec"
        HIGH_SPEC = "high_spec"

    def detect_hardware_tier():
        is_android = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ
        return RuntimeTier.LOW_SPEC_MOBILE if is_android else RuntimeTier.MID_SPEC


@dataclass
class SearchResult:
    source_type: str      # "ROOT_LEDGER" | "SCRATCHPAD" | "ARCHIVED_TURN"
    source_id: str        # task_slug, agent_id, or turn filename
    section: str          # e.g., "invariants", "hypotheses", "tool_result"
    content: str
    relevance_score: float


class FederatedTurnRetriever:
    """
    Hardware-adaptive retriever capable of scanning across:
    1. Shared Root Ledgers (.codex/ledger/*-root.json)
    2. Private Worker Scratchpads (.codex/ledger/scratchpads/*.json)
    3. Archived Page-Turn Histories (.codex/history/*.jsonl)
    """
    def __init__(self, workspace_root: str):
        self.workspace = Path(workspace_root)
        self.ledger_dir = self.workspace / ".codex" / "ledger"
        self.history_dir = self.workspace / ".codex" / "history"
        self.scratchpad_dir = self.ledger_dir / "scratchpads"
        self.tier = detect_hardware_tier()

    def search(
        self,
        query: str,
        task_slug: Optional[str] = None,
        include_scratchpads: bool = True,
        include_history: bool = True,
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Executes a federated search across all agent ledger layers.
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        candidates: List[SearchResult] = []

        # 1. Search Shared Root Ledgers
        candidates.extend(self._search_root_ledgers(query_tokens, task_slug))

        # 2. Search Private Worker Scratchpads
        if include_scratchpads:
            candidates.extend(self._search_scratchpads(query_tokens))

        # 3. Search Historical Turned Pages / Tool Execution Logs
        if include_history:
            candidates.extend(self._search_history_logs(query_tokens))

        # Sort results by relevance descending
        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates[:top_k]

    def _search_root_ledgers(self, query_tokens: List[str], task_slug: Optional[str]) -> List[SearchResult]:
        results = []
        if not self.ledger_dir.exists():
            return results

        pattern = f"{task_slug}-root.json" if task_slug else "*-root.json"
        for state_file in self.ledger_dir.glob(pattern):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            slug = data.get("task_slug", state_file.stem)

            # Match Invariants
            for inv in data.get("invariants", []):
                score = self._compute_score(query_tokens, inv)
                if score > 0:
                    author = data.get("invariant_authors", {}).get(inv, "system")
                    results.append(SearchResult(
                        source_type="ROOT_LEDGER",
                        source_id=slug,
                        section=f"invariant (author: {author})",
                        content=inv,
                        relevance_score=score * 1.3  # Invariants receive priority weighting
                    ))

            # Match Confirmed Facts
            for fact in data.get("verified_facts", []):
                score = self._compute_score(query_tokens, fact)
                if score > 0:
                    results.append(SearchResult(
                        source_type="ROOT_LEDGER",
                        source_id=slug,
                        section="verified_fact",
                        content=fact,
                        relevance_score=score * 1.2
                    ))

            # Match Milestones
            for ms in data.get("completed_milestones", []) + data.get("pending_milestones", []):
                score = self._compute_score(query_tokens, ms)
                if score > 0:
                    results.append(SearchResult(
                        source_type="ROOT_LEDGER",
                        source_id=slug,
                        section="milestone",
                        content=ms,
                        relevance_score=score
                    ))
        return results

    def _search_scratchpads(self, query_tokens: List[str]) -> List[SearchResult]:
        results = []
        if not self.scratchpad_dir.exists():
            return results

        for sp_file in self.scratchpad_dir.glob("*.json"):
            try:
                with open(sp_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            agent_id = data.get("agent_id", sp_file.stem)
            role = data.get("active_role", "unknown")

            # Search Hypotheses
            for h in data.get("hypotheses", []):
                score = self._compute_score(query_tokens, h)
                if score > 0:
                    results.append(SearchResult(
                        source_type="SCRATCHPAD",
                        source_id=f"{agent_id} ({role})",
                        section="hypothesis",
                        content=h,
                        relevance_score=score * 0.9
                    ))

            # Search Candidate/Staged Invariants
            for ci in data.get("candidate_invariants", []):
                score = self._compute_score(query_tokens, ci)
                if score > 0:
                    results.append(SearchResult(
                        source_type="SCRATCHPAD",
                        source_id=f"{agent_id} ({role})",
                        section="staged_invariant",
                        content=ci,
                        relevance_score=score * 1.0
                    ))

            # Search Local Notes
            for note in data.get("local_notes", []):
                score = self._compute_score(query_tokens, note)
                if score > 0:
                    results.append(SearchResult(
                        source_type="SCRATCHPAD",
                        source_id=f"{agent_id} ({role})",
                        section="local_note",
                        content=note,
                        relevance_score=score * 0.8
                    ))
        return results

    def _search_history_logs(self, query_tokens: List[str]) -> List[SearchResult]:
        results = []
        if not self.history_dir.exists():
            return results

        for log_file in self.history_dir.glob("*.jsonl"):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        text_corpus = f"{entry.get('payload', '')} {entry.get('result_summary', '')}"
                        score = self._compute_score(query_tokens, text_corpus)
                        if score > 0:
                            results.append(SearchResult(
                                source_type="ARCHIVED_TURN",
                                source_id=log_file.stem,
                                section=f"tool:{entry.get('tool', 'unknown')}",
                                content=entry.get("result_summary", "")[:250],
                                relevance_score=score * 0.85
                            ))
            except Exception:
                continue
        return results

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Low-RAM tokenization: alphanumeric lower-cased tokens > 2 chars."""
        return [tok for tok in re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", text.lower())]

    def _compute_score(self, query_tokens: List[str], target_text: str) -> float:
        """
        Hardware-adaptive scoring:
        On low-spec/mobile, executes an exact frequency + coverage calculation.
        """
        if not target_text:
            return 0.0

        target_tokens = self._tokenize(target_text)
        if not target_tokens:
            return 0.0

        target_set = set(target_tokens)
        matches = 0
        freq = 0

        for q in query_tokens:
            if q in target_set:
                matches += 1
                freq += target_tokens.count(q)

        if matches == 0:
            return 0.0

        # BM25-style saturation: rewards coverage across unique query terms
        coverage_ratio = matches / len(query_tokens)
        density = freq / len(target_tokens)
        return round((coverage_ratio * 0.7) + (min(density, 1.0) * 0.3), 4)
