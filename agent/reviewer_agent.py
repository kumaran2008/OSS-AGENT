"""
Backward-compatible facade for the Code Reviewer agent.
Delegates to modular agent.qa.reviewer_agent.ReviewerAgent.
"""
from agent.qa.reviewer_agent import ReviewerAgent

__all__ = ["ReviewerAgent"]
