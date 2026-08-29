from pathlib import Path
from typing import Tuple
from tools.shell import SafeShell


class GitTools:
    def __init__(self, repo_dir: Path):
        self.shell = SafeShell(repo_dir)

    def checkout_branch(self, branch_name: str) -> Tuple[int, str, str]:
        return self.shell.execute(f"git checkout -b {branch_name}", auto_approve_override=True)

    def get_diff(self) -> str:
        code, stdout, _ = self.shell.execute("git diff", auto_approve_override=True)
        return stdout if code == 0 else ""

    def get_history(self, max_commits: int = 5) -> str:
        code, stdout, _ = self.shell.execute(f"git log -n {max_commits} --oneline", auto_approve_override=True)
        return stdout if code == 0 else ""

    def commit_all(self, message: str) -> Tuple[int, str, str]:
        self.shell.execute("git add -A", auto_approve_override=True)
        escaped_msg = message.replace('"', '\\"')
        return self.shell.execute(f'git commit -m "{escaped_msg}"')

    def push(self, remote: str, branch: str) -> Tuple[int, str, str]:
        return self.shell.execute(f"git push {remote} {branch}")
