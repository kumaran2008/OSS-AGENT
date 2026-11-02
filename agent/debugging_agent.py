"""
Backward-compatible facade for the QA / Debugging agent.
Delegates to modular agent.qa.tester_agent.TesterAgent.
"""
from agent.qa.tester_agent import TesterAgent
from agent.masons import extract_code_block as _extract_code_block

# Retain DebuggingAgent as alias for existing orchestrator calls
class DebuggingAgent(TesterAgent):
    pass

__all__ = ["DebuggingAgent", "TesterAgent"]
