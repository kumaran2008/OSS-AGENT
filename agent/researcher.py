"""
Backward-compatible facade for the Repository Research Agent.
Delegates to modular agent.research.repository_researcher.RepositoryResearchAgent.
"""
from agent.research.repository_researcher import RepositoryResearchAgent

__all__ = ["RepositoryResearchAgent"]
