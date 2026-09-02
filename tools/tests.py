import re
from pathlib import Path
from typing import Set, Tuple
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

    def parse_failing_tests(self, test_output: str) -> Set[str]:
        """
        Extracts specific failing test node IDs from test output to enable
        precise baseline vs post-patch differential comparisons. Handles
        both pytest and unittest failure formats.
        """
        failing_nodes = set()

        # Matches Pytest summary failures: FAILED tests/test_proxy.py::test_use_proxy
        pytest_failures = re.findall(r"FAILED\s+([^\s:]+(?:::[^\s:]+)+)", test_output)
        failing_nodes.update(pytest_failures)

        # Matches Pytest ERROR setup/teardown failures: ERROR tests/test_proxy.py::test_use_proxy
        pytest_errors = re.findall(r"ERROR\s+([^\s:]+(?:::[^\s:]+)+)", test_output)
        failing_nodes.update(pytest_errors)

        # Matches standard unittest failure patterns: FAIL: test_proxy (tests.test_proxy.ProxyTestCase)
        unittest_failures = re.findall(r"(?:FAIL|ERROR):\s+([^\s]+)\s+\(([^)]+)\)", test_output)
        for test_name, test_class in unittest_failures:
            failing_nodes.add(f"{test_class}::{test_name}")

        return failing_nodes

    def _has_c_source_files(self) -> bool:
        """Quick check for .c/.cpp/.h files at the repo root or one level
        deep, to avoid misidentifying an unrelated Makefile-based project."""
        try:
            for pattern in ("*.c", "*.cpp", "*.h", "*.hpp"):
                if list(self.workspace_root.glob(pattern)) or list(self.workspace_root.glob(f"src/{pattern}")):
                    return True
        except Exception:
            pass
        return False

    def _detect_language(self) -> str:
        """
        Detects the primary language/build system of the cloned repo by
        checking for its characteristic config file. Checked in a fixed
        order — a repo could technically have multiple (e.g. Python
        bindings in a Rust project), so this picks the most likely
        primary based on common conventions.
        """
        has = lambda fname: (self.workspace_root / fname).exists()

        if has("Cargo.toml"):
            return "rust"
        if has("go.mod"):
            return "go"
        if has("package.json"):
            return "node"
        if has("CMakeLists.txt"):
            return "cpp_cmake"
        if has("meson.build"):
            return "cpp_meson"
        if has("Makefile") and self._has_c_source_files():
            return "c_make"
        if has("pyproject.toml") or has("requirements.txt") or has("setup.py") or has("pytest.ini"):
            return "python"
        return "unknown"

    def run_suite(self) -> Tuple[int, str]:
        guard_result = self.preflight_check()
        if not guard_result.ok:
            return -2, format_guard_report(guard_result)

        language = self._detect_language()

        if language == "python":
            if (self.workspace_root / "pytest.ini").exists() or (self.workspace_root / "tests").exists():
                code, stdout, stderr = self.shell.execute("python -m pytest", auto_approve_override=True)
                return code, stdout + "\n" + stderr
            if (self.workspace_root / "test").exists():
                code, stdout, stderr = self.shell.execute("python -m unittest discover", auto_approve_override=True)
                return code, stdout + "\n" + stderr
            return 0, "No standard Python test framework detected. Skipping."

        if language == "node":
            package_json = self.workspace_root / "package.json"
            try:
                import json as _json
                scripts = _json.loads(package_json.read_text()).get("scripts", {})
            except Exception:
                scripts = {}
            if "test" in scripts:
                code, stdout, stderr = self.shell.execute("npm test", auto_approve_override=True)
                return code, stdout + "\n" + stderr
            return 0, "package.json has no 'test' script defined. Skipping."

        if language == "rust":
            code, stdout, stderr = self.shell.execute("cargo test", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        if language == "go":
            code, stdout, stderr = self.shell.execute("go test ./...", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        if language == "cpp_cmake":
            build_dir = self.workspace_root / "build"
            if not build_dir.exists():
                configure_code, c_stdout, c_stderr = self.shell.execute(
                    "cmake -S . -B build", auto_approve_override=True
                )
                if configure_code != 0:
                    return configure_code, c_stdout + "\n" + c_stderr
                build_code, b_stdout, b_stderr = self.shell.execute(
                    "cmake --build build", auto_approve_override=True
                )
                if build_code != 0:
                    return build_code, b_stdout + "\n" + b_stderr
            code, stdout, stderr = self.shell.execute(
                "ctest --test-dir build --output-on-failure", auto_approve_override=True
            )
            return code, stdout + "\n" + stderr

        if language == "cpp_meson":
            build_dir = self.workspace_root / "builddir"
            if not build_dir.exists():
                setup_code, s_stdout, s_stderr = self.shell.execute("meson setup builddir", auto_approve_override=True)
                if setup_code != 0:
                    return setup_code, s_stdout + "\n" + s_stderr
            code, stdout, stderr = self.shell.execute("meson test -C builddir", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        if language == "c_make":
            code, stdout, stderr = self.shell.execute("make test", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        return 0, "No recognized test framework detected for this repository. Skipping."

    def run_lint(self) -> Tuple[int, str]:
        language = self._detect_language()

        if language == "python" and ((self.workspace_root / ".flake8").exists()
                                      or (self.workspace_root / "pyproject.toml").exists()):
            code, stdout, stderr = self.shell.execute("flake8 .", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        if language == "node":
            package_json = self.workspace_root / "package.json"
            try:
                import json as _json
                scripts = _json.loads(package_json.read_text()).get("scripts", {})
            except Exception:
                scripts = {}
            if "lint" in scripts:
                code, stdout, stderr = self.shell.execute("npm run lint", auto_approve_override=True)
                return code, stdout + "\n" + stderr

        if language == "rust":
            code, stdout, stderr = self.shell.execute("cargo clippy", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        if language == "go":
            code, stdout, stderr = self.shell.execute("go vet ./...", auto_approve_override=True)
            return code, stdout + "\n" + stderr

        if language in ("cpp_cmake", "cpp_meson", "c_make"):
            from shutil import which
            if which("cppcheck"):
                code, stdout, stderr = self.shell.execute(
                    f"cppcheck --enable=warning {self.workspace_root}", auto_approve_override=True
                )
                return code, stdout + "\n" + stderr
            return 0, "cppcheck not installed on host — skipping C/C++ lint."

        return 0, "No linter detected for this repository. Skipping."
