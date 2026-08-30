from pathlib import Path
from typing import Tuple
from tools.shell import SafeShell
from tools.repo_guard import RepoGuard, format_guard_report


class TestRunner:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.shell = SafeShell(workspace_root)
        self.guard = RepoGuard()

    def preflight_check(self):
        """Returns a GuardResult. Call this before run_suite() so missing
        host dependencies are caught before wasting an LLM debug call."""
        return self.guard.inspect_workspace(self.workspace_root)

    def run_suite(self) -> Tuple[int, str]:
        guard_result = self.preflight_check()
        if not guard_result.ok:
            return -2, format_guard_report(guard_result)

        if (self.workspace_root / "pytest.ini").exists() or (self.workspace_root / "tests").exists():
            code, stdout, stderr = self.shell.execute("python -m pytest", auto_approve_override=True)
            return code, stdout + "\n" + stderr
        if (self.workspace_root / "test").exists():
            code, stdout, stderr = self.shell.execute("python -m unittest discover", auto_approve_override=True)
            return code, stdout + "\n" + stderr
        return 0, "No standard Python test framework detected. Skipping."

    def run_lint(self) -> Tuple[int, str]:
        if (self.workspace_root / ".flake8").exists() or (self.workspace_root / "pyproject.toml").exists():
            code, stdout, stderr = self.shell.execute("flake8 .", auto_approve_override=True)
            return code, stdout + "\n" + stderr
        return 0, "No linter config detected. Skipping."
