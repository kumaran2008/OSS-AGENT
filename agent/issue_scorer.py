"""
Backward-compatible facade for IssueTractabilityScorer.
Delegates to agent.triage.scorer.IssueTractabilityScorer.
"""
from agent.triage.scorer import IssueTractabilityScorer

__all__ = ["IssueTractabilityScorer"]
