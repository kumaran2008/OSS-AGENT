import re
from typing import Dict, List, Union

# Patterns for common credentials, API keys, tokens, and passwords
SECRET_PATTERNS = [
    # GitHub Personal Access Tokens & OAuth
    r"ghp_[a-zA-Z0-9]{36}",
    r"gho_[a-zA-Z0-9]{36}",
    r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}",
    # OpenAI / OpenRouter / Anthropic Keys
    r"sk-or-v1-[a-zA-Z0-9]{64}",
    r"sk-proj-[a-zA-Z0-9_\-]{20,}",
    r"sk-[a-zA-Z0-9]{48}",
    r"sk-ant-[a-zA-Z0-9_\-]{80,}",
    # Google API keys
    r"AIza[0-9A-Za-z_\-]{35}",
    # AWS Credentials
    r"AKIA[0-9A-Z]{16}",
    r"(?i)aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]",
    # JWTs (three base64 segments separated by dots)
    r"eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+",
    # Generic Bearer Tokens & Passwords in ENVs/JSON
    r"(?i)(api[_\-]?key|auth[_\-]?token|password|secret)\s*[:=]\s*['\"][^\n'\"]{6,}['\"]",
]

COMPILED_PATTERNS = [re.compile(p) for p in SECRET_PATTERNS]


def redact_secrets(text: str) -> str:
    """Scrubs sensitive API keys, tokens, and secrets from a string."""
    if not isinstance(text, str):
        return text

    sanitized = text
    for pattern in COMPILED_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


def sanitize_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Sanitizes a list of OpenAI-style chat completion message dictionaries."""
    sanitized_messages = []
    for msg in messages:
        clean_msg = msg.copy()
        if "content" in clean_msg and isinstance(clean_msg["content"], str):
            clean_msg["content"] = redact_secrets(clean_msg["content"])
        sanitized_messages.append(clean_msg)
    return sanitized_messages
