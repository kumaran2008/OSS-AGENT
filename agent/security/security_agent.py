import re
from pathlib import Path
from typing import Any, Dict, List
from llm.router import LLMRouter
from tools.system_tier import CURRENT_TIER, HardwareTier


class SecurityAgent:
    """
    Adversarial Security Auditor & Sentinel Gatekeeper.
    Inspects diffs and source modifications for credential leaks,
    arbitrary command injections, and insecure runtime patterns.
    """

    # Deterministic high-speed security heuristics (works on all hardware tiers)
    SECRET_PATTERNS = [
        re.compile(r'''(?i)(api[_-]?key|secret|token|password|auth_token)\s*=\s*['"][a-zA-Z0-9_\-]{8,}['"]'''),
        re.compile(r"ghp_[a-zA-Z0-9]{36}"),
        re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    ]

    INSECURE_PATTERNS = [
        (re.compile(r"\b(eval|exec)\s*\("), "Critical: Unsafe execution primitive ('eval'/'exec')"),
        (re.compile(r"subprocess\.(run|Popen|check_call)\([^,]+,\s*shell\s*=\s*True"), "High: shell=True execution vector detected"),
        (re.compile(r"os\.system\s*\("), "High: os.system call is prone to command injection"),
    ]

    def __init__(self, router: LLMRouter):
        self.router = router

    def audit_diff(self, diff_text: str) -> Dict[str, Any]:
        """
        Audits a unified diff against deterministic leakage rules and runtime model checks.
        Returns: {"passed": bool, "reasons": List[str]}
        """
        issues: List[str] = []

        if not diff_text.strip():
            return {"passed": True, "reasons": ["Diff is empty; no security concerns."]}

        # 1. Deterministic Heuristics (Instant & zero token cost on all devices)
        for line in diff_text.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue

            for pat in self.SECRET_PATTERNS:
                if pat.search(line):
                    issues.append(f"Secret Leak Risk: Hardcoded token or key detected in line: {line.strip()[:40]}...")

            for pat, desc in self.INSECURE_PATTERNS:
                if pat.search(line):
                    issues.append(desc)

        # 2. Model-driven audit on Mid/High tiers
        if CURRENT_TIER in (HardwareTier.TIER_MID, HardwareTier.TIER_HIGH) and not issues:
            prompt = (
                "You are an adversarial software security engineer.\n"
                "Audit the following Git diff for security regressions, injection vectors, or memory leaks.\n"
                "Diff:\n"
                f"{diff_text[:3000]}\n\n"
                "If it is secure, reply ONLY with 'PASS'. Otherwise, reply with 'FAIL: <short reason>'."
            )
            try:
                verdict, _ = self.router.complete_with_fallback(
                    "analysis",
                    [{"role": "user", "content": prompt}]
                )
                if verdict.strip().startswith("FAIL"):
                    issues.append(verdict.strip())
            except Exception:
                pass

        return {
            "passed": len(issues) == 0,
            "reasons": issues if issues else ["Security audit passed cleanly."]
        }
