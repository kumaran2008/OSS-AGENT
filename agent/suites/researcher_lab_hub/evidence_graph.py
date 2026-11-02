from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from agent.kernel.jev_ai_system1 import jev_ai_brain


@dataclass
class ResearchClaimRecord:
    claim_text: str
    sources: List[str]
    evidence_types: List[str]
    dataset_or_method: str
    confidence: float
    disputed: bool
    contradicting_sources: List[str] = field(default_factory=list)


class EvidenceAndContradictionEngine:
    """Section 6.4: Evidence & Contradiction Engine (Tracks claims across sources and flags disputes)."""

    def audit_research_claims(self, core_claim: str, source_evaluations: List[Dict[str, Any]]) -> ResearchClaimRecord:
        supporting: List[str] = []
        contradicting: List[str] = []

        for ev in source_evaluations:
            src_name = ev.get("source_name", "unknown_source")
            text = ev.get("summary_text", "")
            q_ev = {
                "supports_claim": {"type": "noul", "affirmative_signals": ["improve", "higher", "state-of-the-art", "outperform", "positive", "successful", "effective"]},
                "contradicts_claim": {"type": "noul", "affirmative_signals": ["fail", "no significant", "worse", "contradict", "limit", "drawback", "overfit"]},
            }
            prims = jev_ai_brain.evaluate_primitives(text, q_ev)
            if prims["contradicts_claim"].value:
                contradicting.append(src_name)
            elif prims["supports_claim"].value:
                supporting.append(src_name)

        is_disputed = len(contradicting) > 0 and len(supporting) > 0
        mean_conf = round(sum(ev.get("confidence", 0.85) for ev in source_evaluations) / max(1, len(source_evaluations)), 2)

        return ResearchClaimRecord(
            claim_text=core_claim,
            sources=supporting,
            evidence_types=["empirical_benchmark", "peer_reviewed_paper"],
            dataset_or_method="Cross-Source Literature Audit",
            confidence=mean_conf,
            disputed=is_disputed,
            contradicting_sources=contradicting,
        )


evidence_engine = EvidenceAndContradictionEngine()
