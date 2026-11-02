"""
Backward-compatible facade for the Security Audit agent.
Delegates to modular agent.security.security_agent.SecurityAgent.
"""
from agent.security.security_agent import SecurityAgent

__all__ = ["SecurityAgent"]
