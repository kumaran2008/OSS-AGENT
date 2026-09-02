import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class MissingDependency:
    component: str          # e.g. "pytest module"
    reason: str              # human-readable explanation
    install_command: str     # exact copy-pasteable fix


@dataclass
class GuardResult:
    ok: bool
    repo_name: str
    missing: List[MissingDependency] = field(default_factory=list)


def _detect_platform() -> str:
    if "com.termux" in os.environ.get("PREFIX", ""):
        return "termux"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("win"):
        return "windows"
    return "unknown"


def _install_cmd(binary: str, platform: str, pip_fallback: Optional[str] = None) -> str:
    """Returns the best copy-pasteable install command for a given tool/binary."""
    commands = {
        "termux": {
            "npm": "pkg install nodejs -y",
            "node": "pkg install nodejs -y",
            "cargo": "pkg install rust -y",
            "make": "pkg install make -y",
            "tox": "pip install tox --break-system-packages",
        },
        "mac": {
            "npm": "brew install node",
            "node": "brew install node",
            "cargo": "brew install rust",
            "make": "xcode-select --install",
            "tox": "pip install tox",
        },
        "linux": {
            "npm": "sudo apt install nodejs npm -y",
            "node": "sudo apt install nodejs -y",
            "cargo": "sudo apt install cargo -y",
            "make": "sudo apt install build-essential -y",
            "tox": "pip install tox",
        },
        "windows": {
            "npm": "winget install OpenJS.NodeJS",
            "node": "winget install OpenJS.NodeJS",
            "cargo": "winget install Rustlang.Rust.MSVC",
            "make": "choco install make",
            "tox": "pip install tox",
        },
    }
    platform_map = commands.get(platform, {})
    if binary in platform_map:
        return platform_map[binary]
    if pip_fallback:
        return pip_fallback
    return f"Install '{binary}' manually — no known command for this platform."


class RepoGuard:
    """
    Pre-flight inspector run immediately after cloning a repo, before any
    plan generation or test execution. Detects missing host tools or
    uninstalled dependencies that would cause tests/builds to fail for
    reasons that have nothing to do with the code itself — so the agent
    never wastes an LLM call trying to "fix" a missing system binary.
    """

    def __init__(self):
        self.platform = _detect_platform()

    def inspect_workspace(self, repo_path: Path) -> GuardResult:
        repo_name = repo_path.name
        missing: List[MissingDependency] = []

        has = lambda fname: (repo_path / fname).exists()

        # --- Python projects ---
        if has("pyproject.toml") or has("requirements.txt") or has("setup.py") or has("Pipfile") or has("pytest.ini"):
            if importlib.util.find_spec("pytest") is None:
                missing.append(MissingDependency(
                    component="pytest module",
                    reason="A Python test/build config file was found, but pytest is not installed for this interpreter.",
                    install_command="pip install pytest --break-system-packages"
                        if self.platform == "termux" else "pip install pytest",
                ))

            if has("requirements.txt"):
                unmet = self._check_requirements_installed(repo_path / "requirements.txt")
                if unmet:
                    install_cmd = "pip install -r requirements.txt --break-system-packages" \
                        if self.platform == "termux" else "pip install -r requirements.txt"
                    missing.append(MissingDependency(
                        component="requirements.txt packages",
                        reason=f"{len(unmet)} package(s) declared but not installed: {', '.join(unmet[:5])}"
                               + (" ..." if len(unmet) > 5 else ""),
                        install_command=f"cd {repo_path} && {install_cmd}",
                    ))

        # --- tox ---
        if has("tox.ini") and importlib.util.find_spec("tox") is None:
            missing.append(MissingDependency(
                component="tox",
                reason="tox.ini found but the 'tox' package is not installed.",
                install_command=_install_cmd("tox", self.platform, pip_fallback="pip install tox"),
            ))

        # --- Node projects ---
        if has("package.json"):
            if not (shutil.which("npm") or shutil.which("pnpm") or shutil.which("yarn")):
                missing.append(MissingDependency(
                    component="npm/pnpm/yarn",
                    reason="package.json found but no Node package manager is available on this host.",
                    install_command=_install_cmd("npm", self.platform),
                ))
            elif not (repo_path / "node_modules").exists():
                missing.append(MissingDependency(
                    component="node_modules",
                    reason="package.json found but dependencies have not been installed.",
                    install_command=f"cd {repo_path} && npm install",
                ))

        # --- Rust projects ---
        if has("Cargo.toml") and not shutil.which("cargo"):
            missing.append(MissingDependency(
                component="cargo",
                reason="Cargo.toml found but the Rust toolchain (cargo) is not installed on this host.",
                install_command=_install_cmd("cargo", self.platform),
            ))
        # --- C/C++ projects ---
        if has("CMakeLists.txt") and not shutil.which("cmake"):
            missing.append(MissingDependency(
                component="cmake",
                reason="CMakeLists.txt found but cmake is not installed on this host.",
                install_command={"termux": "pkg install cmake -y", "mac": "brew install cmake",
                                  "linux": "sudo apt install cmake -y",
                                  "windows": "winget install Kitware.CMake"}.get(self.platform, "Install cmake manually"),
            ))
        if has("meson.build") and not shutil.which("meson"):
            missing.append(MissingDependency(
                component="meson",
                reason="meson.build found but meson is not installed on this host.",
                install_command={"termux": "pip install meson ninja --break-system-packages",
                                  "mac": "brew install meson ninja",
                                  "linux": "sudo apt install meson ninja-build -y",
                                  "windows": "pip install meson ninja"}.get(self.platform, "pip install meson ninja"),
            ))
        # --- Makefile-driven builds ---
        if has("Makefile") and not shutil.which("make"):
            missing.append(MissingDependency(
                component="make",
                reason="Makefile found but 'make' is not available on this host.",
                install_command=_install_cmd("make", self.platform),
            ))

        return GuardResult(ok=(len(missing) == 0), repo_name=repo_name, missing=missing)

    def _check_requirements_installed(self, requirements_path: Path) -> List[str]:
        """Returns a list of package names declared in requirements.txt that
        don't appear to be importable/installed. Best-effort, not exhaustive —
        skips version specifiers and extras, just checks the base name."""
        unmet = []
        try:
            lines = requirements_path.read_text(errors="ignore").splitlines()
        except Exception:
            return unmet

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
            if not pkg_name:
                continue
            normalized = pkg_name.replace("-", "_")
            if importlib.util.find_spec(normalized) is None:
                # fall back to checking via pip show, since import name often
                # differs from package name (e.g. python-dotenv -> dotenv)
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "show", pkg_name],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    unmet.append(pkg_name)
        return unmet


def format_guard_report(result: GuardResult) -> str:
    lines = [
        "=" * 60,
        "[HOST ENVIRONMENT / REPO DEPENDENCY MISSING]",
        "=" * 60,
        f"Repository: {result.repo_name}",
        "",
    ]
    for i, dep in enumerate(result.missing, 1):
        lines.append(f"Missing Component #{i}: {dep.component}")
        lines.append(f"  Reason: {dep.reason}")
        lines.append(f"  Fix:    {dep.install_command}")
        lines.append("")
    lines.append("=" * 60)
    lines.append("Run the fix command(s) above, then re-run the agent.")
    lines.append("=" * 60)
    return "\n".join(lines)
