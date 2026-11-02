import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

class GitBridge:
    """Manages git operations for autonomous issue reproduction, branching, and PR submissions."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path

    def _run_git(self, cmd: list) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + cmd,
            cwd=str(self.workspace_path),
            text=True,
            capture_output=True
        )

    def is_git_repo(self) -> bool:
        res = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return res.returncode == 0 and res.stdout.strip() == "true"

    def init_repo(self) -> bool:
        res = self._run_git(["init"])
        return res.returncode == 0

    def checkout_branch(self, branch_name: str) -> bool:
        res = self._run_git(["checkout", "-B", branch_name])
        return res.returncode == 0

    def stage_and_commit(self, message: str) -> Dict[str, Any]:
        self._run_git(["add", "-A"])
        res = self._run_git(["commit", "-m", message])
        return {
            "success": res.returncode == 0,
            "output": res.stdout.strip() if res.returncode == 0 else res.stderr.strip()
        }

    def generate_diff(self) -> str:
        res = self._run_git(["diff", "HEAD~1"])
        if res.returncode != 0:
            res = self._run_git(["diff"])
        return res.stdout

    def create_pull_request(self, title: str, body: str, branch: str) -> Dict[str, Any]:
        """Submits PR using the GitHub CLI (gh) if installed and authenticated."""
        gh_path = subprocess.run(["which", "gh"], capture_output=True, text=True).stdout.strip()
        if not gh_path:
            return {
                "success": False,
                "error": "GitHub CLI ('gh') is not installed. Install with 'pkg install gh'."
            }

        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", branch
        ]
        res = subprocess.run(cmd, cwd=str(self.workspace_path), text=True, capture_output=True)
        if res.returncode == 0:
            return {"success": True, "url": res.stdout.strip()}
        return {"success": False, "error": res.stderr.strip()}
