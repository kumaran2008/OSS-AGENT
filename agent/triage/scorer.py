import re
from typing import Dict, Any, Tuple
from tools.system_tier import CURRENT_TIER, HardwareTier


class IssueTractabilityScorer:
    """
    Computes a deterministic Tractability Index (0-100) from GitHub issue metadata
    before any planning LLM or repository cloning is triggered.
    """

    NEGATIVE_LABELS = {
        "needs-discussion", "rfc", "proposal", "design", "question",
        "wontfix", "blocked", "upstream", "epic", "enhancement", "feature"
    }

    POSITIVE_LABELS = {
        "good first issue", "good-first-issue", "beginner-friendly",
        "bug", "patch", "help wanted", "confirmed", "regression"
    }

    STACK_PATTERNS = [
        r"Traceback \(most recent call last\):",
        r"File \".*?\", line \d+",
        r"Error:.*?\n\s+at ",
        r"panic:.*?\ngoroutine \d+",
        r"Exception in thread \".*?\"",
    ]

    NEGATIVE_PHRASES = [
        r"breaking change",
        r"architectural redesign",
        r"what do you think",
        r"how should we handle",
        r"needs consensus",
    ]

    def score(self, issue: Dict[str, Any]) -> Tuple[int, str]:
        body = issue.get("body", "") or ""
        comments = issue.get("comments", 0)
        labels = [
            l.get("name", "").lower() if isinstance(l, dict) else str(l).lower()
            for l in issue.get("labels", [])
        ]

        score = 50
        factors = []

        # 1. Label Analysis
        for label in labels:
            if label in self.NEGATIVE_LABELS:
                score -= 30
                factors.append(f"-30 label:{label}")
            if label in self.POSITIVE_LABELS:
                score += 20
                factors.append(f"+20 label:{label}")

        # 2. Contention via Comments
        if comments == 0:
            score += 5
            factors.append("+5 untouched")
        elif comments > 10:
            score -= 30
            factors.append(f"-30 high_contention({comments} comments)")
        elif comments > 5:
            score -= 15
            factors.append(f"-15 moderate_contention({comments} comments)")

        # 3. Code Evidence & Stack Traces
        has_stack = any(re.search(p, body) for p in self.STACK_PATTERNS)
        if has_stack:
            score += 25
            factors.append("+25 stack_trace_present")

        if "```" in body and not has_stack:
            score += 10
            factors.append("+10 code_block_repro")

        # 4. Explicit File or Line Number References
        file_ref = re.search(r"[\w\/\.-]+\.(py|js|ts|go|rs|cpp|c|java):(\d+)?", body)
        if file_ref:
            score += 15
            factors.append(f"+15 targeted_file({file_ref.group(0)})")

        # 5. Contentious Phrasing
        for phrase in self.NEGATIVE_PHRASES:
            if re.search(phrase, body, re.IGNORECASE):
                score -= 20
                factors.append(f"-20 debate_phrase('{phrase}')")
                break

        # 6. Tier-Adaptive Checks
        if CURRENT_TIER == HardwareTier.TIER_LOW:
            if len(body) > 12000:
                score -= 20
                factors.append("-20 excessive_body_size_for_edge")
        else:
            if "steps to reproduce" in body.lower():
                score += 10
                factors.append("+10 repro_steps_defined")

        final_score = max(0, min(100, score))
        summary = ", ".join(factors) if factors else "baseline"
        return final_score, summary
