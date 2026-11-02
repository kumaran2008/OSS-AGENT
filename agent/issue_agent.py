"""
Backward-compatible facade for IssueAgent.
Delegates to agent.triage.selector.IssueAgent.
"""
from agent.triage.selector import IssueAgent

__all__ = ["IssueAgent"]
