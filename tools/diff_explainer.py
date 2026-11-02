import re
import shutil
import subprocess
from typing import List, Dict, Any
from tools.system_tier import CURRENT_TIER, HardwareTier

class DiffHunkExplainer:
    """
    Parses patch diffs into categorized hunks (Core Fix vs. Formatting/Churn)
    with structural diff tool support (difftastic) and low-tier regex fallback.
    """

    def __init__(self):
        self.has_difftastic = shutil.which("difft") is not None

    def get_structural_diff(self, file_a: str, file_b: str) -> str:
        """Uses difftastic on desktop/server, falls back to standard diff on Termux."""
        if self.has_difftastic and CURRENT_TIER != HardwareTier.TIER_LOW:
            res = subprocess.run(["difft", "--color", "never", file_a, file_b], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout:
                return res.stdout

        res = subprocess.run(["git", "diff", "--no-index", file_a, file_b], capture_output=True, text=True)
        return res.stdout

    def parse_hunks(self, raw_diff: str) -> List[Dict[str, Any]]:
        """Parses unified git diff into individual hunk objects with classification."""
        if not raw_diff.strip():
            return []

        hunks = []
        current_file = None
        current_hunk = None

        for line in raw_diff.splitlines():
            if line.startswith("diff --git"):
                parts = line.split(" ")
                current_file = parts[-1].replace("b/", "")
                continue

            if line.startswith("@@"):
                if current_hunk:
                    self._classify_hunk(current_hunk)
                    hunks.append(current_hunk)
                current_hunk = {
                    "file": current_file or "unknown",
                    "header": line,
                    "added": [],
                    "removed": [],
                    "classification": "UNKNOWN",
                    "summary": ""
                }
                continue

            if current_hunk is not None:
                if line.startswith("+") and not line.startswith("+++"):
                    current_hunk["added"].append(line[1:])
                elif line.startswith("-") and not line.startswith("---"):
                    current_hunk["removed"].append(line[1:])

        if current_hunk:
            self._classify_hunk(current_hunk)
            hunks.append(current_hunk)

        return hunks

    def _classify_hunk(self, hunk: Dict[str, Any]) -> None:
        added_text = "".join(hunk["added"]).strip()
        removed_text = "".join(hunk["removed"]).strip()

        # Whitespace / formatting check
        if re.sub(r"\s+", "", added_text) == re.sub(r"\s+", "", removed_text):
            hunk["classification"] = "CHURN"
            hunk["summary"] = "Whitespace or code indentation reformatting."
            return

        # Import modifications
        if all(re.match(r"^(import|from)\s+", l.strip()) for l in hunk["added"] if l.strip()):
            hunk["classification"] = "DEPENDENCY"
            hunk["summary"] = "Module import modification."
            return

        # Functional Logic Patch
        hunk["classification"] = "CORE_FIX"
        hunk["summary"] = f"Alters logic in {hunk['file']} (+{len(hunk['added'])} / -{len(hunk['removed'])} lines)"

    def format_review_summary(self, raw_diff: str) -> str:
        """Generates an audit report suitable for human PR reviews."""
        hunks = self.parse_hunks(raw_diff)
        if not hunks:
            return "No structural code modifications detected."

        core_fixes = [h for h in hunks if h["classification"] == "CORE_FIX"]
        churn = [h for h in hunks if h["classification"] in ("CHURN", "DEPENDENCY")]

        lines = [
            f"### Structural Diff Audit ({len(hunks)} hunks analyzed)",
            f"**Core Functional Changes ({len(core_fixes)}):**"
        ]
        for c in core_fixes:
            lines.append(f"- `{c['file']}`: {c['summary']}")

        if churn:
            lines.append(f"\n**Secondary / Formatting Churn ({len(churn)}):**")
            for ch in churn:
                lines.append(f"- `{ch['file']}`: {ch['summary']}")

        return "\n".join(lines)

