import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Tuple
from agent.security.security_agent import SecurityAgent


class SentinelSecurityError(PermissionError):
    """Raised when an agent action violates active Sentinel safety policies."""
    pass


class SentinelMesh:
    """
    Active runtime security mesh that enforces security policies across
    all subagents, file I/O operations, and tool executions.
    """

    DANGEROUS_COMMANDS = [
        re.compile(r"\brm\s+(-[rfRF]{1,4}\s+[/~]|\s+--no-preserve-root)"),
        re.compile(r"\bmkfs(\.\w+)?\s+"),
        re.compile(r"\bdd\s+if=.*?of=(/dev/[a-z]+|/dev/sd)"),
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),  # Fork bomb
        re.compile(r">\s*(/etc/|/boot/|/sys/|/proc/)"),
        re.compile(r"\b(curl|wget)\s+.*?\s*\|\s*(bash|sh|python)"),  # Blind piped execution
    ]

    def __init__(self, router=None, strict_mode: bool = True):
        self.router = router
        self.strict_mode = strict_mode
        self.auditor = SecurityAgent(router)

    def validate_command(self, command: str) -> Tuple[bool, str]:
        """
        Scans a shell command before subprocess execution.
        Returns (is_safe, reason).
        """
        cmd_str = command.strip()
        if not cmd_str:
            return True, "Empty command."

        for pattern in self.DANGEROUS_COMMANDS:
            if pattern.search(cmd_str):
                reason = f"Command blocked by Sentinel: dangerous system-level pattern detected ({cmd_str[:50]})."
                if self.strict_mode:
                    raise SentinelSecurityError(reason)
                return False, reason

        return True, "Command verified by Sentinel."

    def validate_file_write(self, file_path: str, content: str) -> Tuple[bool, str]:
        """
        Audits file content for credential leaks or dangerous primitives before writing to disk.
        """
        target = Path(file_path)

        # Block traversal outside allowed directories or modification of critical configs
        blocked_names = [".bashrc", ".bash_profile", ".zshrc", ".profile", "authorized_keys", "id_rsa"]
        if target.name in blocked_names:
            reason = f"Write blocked by Sentinel: target file '{target.name}' is a protected credential/profile path."
            if self.strict_mode:
                raise SentinelSecurityError(reason)
            return False, reason

        # Convert write into synthetic diff for SecurityAgent rules
        synthetic_diff = "\n".join(f"+{line}" for line in content.splitlines()[:500])
        audit = self.auditor.audit_diff(synthetic_diff)
        if not audit["passed"]:
            reasons = "; ".join(audit["reasons"])
            reason = f"Write blocked by Sentinel: {reasons}"
            if self.strict_mode:
                raise SentinelSecurityError(reason)
            return False, reason

        return True, "File write verified by Sentinel."

    def audit_patch(self, diff_text: str) -> Dict[str, Any]:
        """
        Validates a full git unified diff before branch merging or PR staging.
        """
        return self.auditor.audit_diff(diff_text)
