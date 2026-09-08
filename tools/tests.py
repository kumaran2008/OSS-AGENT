import os
import shutil
import subprocess
from pathlib import Path
from typing import Set, Tuple, Optional
from tools.shell import SafeShell
from tools.repo_guard import RepoGuard, format_guard_report


class TestRunner:
    """
    Executes repo test suites and linter passes across multiple languages.
    When Docker is available on the host, wraps test execution in an
    isolated sandbox container (no network, memory/CPU capped) to limit
    what an untrusted repository's test suite can do. Falls back to
    direct host execution when Docker isn't available (e.g. Termux).

    All execution — Docker or host — still passes through SafeShell, so
    the existing confirmation prompt and dangerous-command blocklist stay
    in effect regardless of sandboxing mode. Docker adds a second layer
    of protection; it does not replace the first.
    """

    def __init__(self, workspace_root: Path, use_docker: bool = True):
        self.workspace_root = workspace_root
        self.shell = SafeShell(workspace_root)
        self.guard = RepoGuard()
        self.use_docker = use_docker and shutil.which("docker") is not None
        self.docker_image = os.getenv("AGENT_DOCKER_IMAGE", "python:3.11-slim")

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
        import re
        failing_nodes = set()

        pytest_failures = re.findall(r"FAILED\s+([^\s:]+(?:::[^\s:]+)+)", test_output)
        failing_nodes.update(pytest_failures)

        pytest_errors = re.findall(r"ERROR\s+([^\s:]+(?:::[^\s:]+)+)", test_output)
        failing_nodes.update(pytest_errors)

        unittest_failures = re.findall(r"(?:FAIL|ERROR):\s+([^\s]+)\s+\(([^)]+)\)", test_output)
        for test_name, test_class in unittest_failures:
            failing_nodes.add(f"{test_class}::{test_name}")

        return failing_nodes

    def _has_c_source_files(self) -> bool:
        try:
            for pattern in ("*.c", "*.cpp", "*.h", "*.hpp"):
                if list(self.workspace_root.glob(pattern)) or list(self.workspace_root.glob(f"src/{pattern}")):
                    return True
        except Exception:
            pass
        return False

    def _detect_language(self) -> str:
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

    def _run_command(self, cmd: str) -> Tuple[int, str]:
        """
        Runs a command either wrapped in a Docker sandbox or directly on
        the host — either way, through SafeShell, so confirmation and the
        dangerous-command blocklist still apply.
        """
        if self.use_docker:
            docker_cmd = (
                f"docker run --rm --network none "
                f"-v {self.workspace_root}:/workspace -w /workspace "
                f"--memory 2g --cpus 2.0 "
                f"{self.docker_image} sh -c \"{cmd}\""
            )
            print(f"[TestRunner] Executing via Docker sandbox ({self.docker_image}): `{cmd}`")
            code, stdout, stderr = self.shell.execute(docker_cmd, auto_approve_override=True)
        else:
            print(f"[TestRunner] Executing via host shell (no Docker available): `{cmd}`")
            code, stdout, stderr = self.shell.execute(cmd, auto_approve_override=True)
        return code, stdout + "\n" + stderr

    def run_suite(self) -> Tuple[int, str]:
        guard_result = self.preflight_check()
        if not guard_result.ok:
            return -2, format_guard_report(guard_result)

        language = self._detect_language()

        if language == "python":
            if (self.workspace_root / "pytest.ini").exists() or (self.workspace_root / "tests").exists():
                return self._run_command("python -m pytest")
            if (self.workspace_root / "test").exists():
                return self._run_command("python -m unittest discover")
            return 0, "No standard Python test framework detected. Skipping."

        if language == "node":
            package_json = self.workspace_root / "package.json"
            try:
                import json as _json
                scripts = _json.loads(package_json.read_text()).get("scripts", {})
            except Exception:
                scripts = {}
            if "test" not in scripts:
                return 0, "package.json has no 'test' script defined. Skipping."
            test_cmd = resolve_package_manager_test_command(self.workspace_root, "test")
            if not test_cmd:
                return -2, "No usable Node package manager (npm/pnpm/yarn/bun) found to run tests."
            return self._run_command(test_cmd)

        if language == "rust":
            return self._run_command("cargo test")

        if language == "go":
            return self._run_command("go test ./...")

        if language == "cpp_cmake":
            build_dir = self.workspace_root / "build"
            if not build_dir.exists():
                configure_code, configure_output = self._run_command("cmake -S . -B build")
                if configure_code != 0:
                    return configure_code, configure_output
                build_code, build_output = self._run_command("cmake --build build")
                if build_code != 0:
                    return build_code, build_output
            return self._run_command("ctest --test-dir build --output-on-failure")

        if language == "cpp_meson":
            build_dir = self.workspace_root / "builddir"
            if not build_dir.exists():
                setup_code, setup_output = self._run_command("meson setup builddir")
                if setup_code != 0:
                    return setup_code, setup_output
            return self._run_command("meson test -C builddir")

        if language == "c_make":
            return self._run_command("make test")

        return 0, "No recognized test framework detected for this repository. Skipping."

    def run_lint(self) -> Tuple[int, str]:
        language = self._detect_language()

        if language == "python" and ((self.workspace_root / ".flake8").exists()
                                      or (self.workspace_root / "pyproject.toml").exists()):
            return self._run_command("flake8 .")

        if language == "node":
            package_json = self.workspace_root / "package.json"
            try:
                import json as _json
                scripts = _json.loads(package_json.read_text()).get("scripts", {})
            except Exception:
                scripts = {}
            if "lint" in scripts:
                lint_cmd = resolve_package_manager_test_command(self.workspace_root, "lint")
                if lint_cmd:
                    return self._run_command(lint_cmd)

        if language == "rust":
            return self._run_command("cargo clippy")

        if language == "go":
            return self._run_command("go vet ./...")

        if language in ("cpp_cmake", "cpp_meson", "c_make"):
            if shutil.which("cppcheck") or self.use_docker:
                return self._run_command(f"cppcheck --enable=warning .")
            return 0, "cppcheck not installed on host — skipping C/C++ lint."

        return 0, "No linter detected for this repository. Skipping."



def detect_node_package_manager(repo_dir: Path) -> Optional[str]:
    """
    Detects which Node package manager a repo actually uses. Lockfiles
    are checked first since they're the most reliable signal; the
    package.json 'packageManager' field is checked as a fallback only
    for its exact declared field, not raw substring search across the
    whole file (which risks false positives from unrelated content).

    Bun is never selected on Termux/Android — it does not officially
    support that platform and its native binary reliably fails
    post-install there, even when the JS wrapper appears to install
    successfully. Falls back to npm in that case.
    """
    repo_dir = Path(repo_dir).resolve()
    package_json = repo_dir / "package.json"

    if not package_json.exists():
        return None

    is_termux = "TERMUX_VERSION" in os.environ or "com.termux" in os.environ.get("PREFIX", "")
    has = lambda fname: (repo_dir / fname).exists()

    # 1. Lockfiles are the most reliable signal — check first.
    if has("pnpm-lock.yaml") or has("pnpm-workspace.yaml"):
        return "pnpm"
    if has("yarn.lock"):
        return "yarn"
    if has("bun.lockb"):
        return "npm" if is_termux else "bun"

    # 2. Fall back to package.json's declared "packageManager" field,
    # parsed properly rather than via raw substring search.
    try:
        import json as _json
        data = _json.loads(package_json.read_text(encoding="utf-8"))
        declared = data.get("packageManager", "")
        if declared.startswith("pnpm"):
            return "pnpm"
        if declared.startswith("yarn"):
            return "yarn"
        if declared.startswith("bun"):
            return "npm" if is_termux else "bun"
    except Exception:
        pass

    return "npm"


def auto_install_package_manager(manager: str) -> bool:
    """
    Automatically downloads and installs the required package manager globally
    if it is missing on the host system.
    """
    if shutil.which(manager):
        return True

    print(f"\n[Auto-Installer] Missing package manager '{manager}' detected.")
    print(f"[Auto-Installer] Automatically downloading and installing '{manager}' globally...")

    install_cmds = {
        "pnpm": "npm install -g pnpm",
        "yarn": "npm install -g yarn",
        "bun": "npm install -g bun",
    }

    cmd = install_cmds.get(manager)
    if not cmd:
        return False

    try:
        # Run auto-download in background
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and shutil.which(manager):
            print(f"[Auto-Installer] Successfully installed '{manager}'!")
            return True
        else:
            print(f"[Auto-Installer Warning] Global install failed, attempting fallback...")
    except Exception as e:
        print(f"[Auto-Installer Error] Failed to auto-download {manager}: {e}")

    return False


def resolve_package_manager_command(repo_dir: Path) -> Optional[str]:
    """
    Given the detected package manager, automatically ensures the tool is downloaded/installed
    and returns the install command to execute for the repository.
    """
    manager = detect_node_package_manager(repo_dir)
    if manager is None:
        return None

    # detect_node_package_manager() already excludes bun on Termux, so
    # 'manager' here is never "bun" on that platform — this is just a
    # defensive second check in case this function is ever called
    # directly with a manager string from elsewhere.
    is_termux = "TERMUX_VERSION" in os.environ or "com.termux" in os.environ.get("PREFIX", "")
    if manager == "bun" and is_termux:
        manager = "npm"

    # 1. Auto-download missing package manager if not present
    if not shutil.which(manager):
        auto_install_package_manager(manager)

    # 2. Return primary command if binary now exists
    if shutil.which(manager):
        return f"{manager} install"

    # 3. Fallbacks if global auto-install failed or lacks permissions
    if shutil.which("corepack"):
        return f"corepack {manager} install"
    if shutil.which("npx"):
        return f"npx {manager} install"

    if manager == "pnpm":
        return "npx pnpm install"

    return f"{manager} install"


def resolve_package_manager_test_command(repo_dir: Path, script_name: str = "test") -> Optional[str]:
    """
    Returns the correct command to run a package.json script (test or lint)
    using whichever package manager this repo actually uses.
    """
    manager = detect_node_package_manager(repo_dir)
    if manager is None:
        return None

    if not shutil.which(manager):
        auto_install_package_manager(manager)

    if manager == "bun":
        return f"bun run {script_name}"
    if manager == "npm":
        return f"npm run {script_name}" if script_name != "test" else "npm test"

    if script_name == "test":
        return f"{manager} test"
    return f"{manager} run {script_name}"
