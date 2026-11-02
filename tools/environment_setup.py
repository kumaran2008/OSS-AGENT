import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


def _detect_platform() -> str:
    if "com.termux" in os.environ.get("PREFIX", "") or "TERMUX_VERSION" in os.environ:
        return "termux"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("win"):
        return "windows"
    return "unknown"


class EnvironmentBootstrapper:
    """
    On-demand dependency & environment bootstrapper.
    Invoked strictly after cloning a target repository to install only
    the compilers, package managers, and runtimes required by that repo.
    """

    def __init__(self):
        self.platform = _detect_platform()
        self.is_termux = self.platform == "termux"

    def _run_cmd(self, cmd: List[str]) -> bool:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            return res.returncode == 0
        except Exception:
            return False

    def bootstrap_environment(self) -> None:
        """Deprecated global startup installer. Kept as no-op for backward compatibility."""
        pass

    def bootstrap_for_repo(self, repo_dir: Optional[Path]) -> None:
        """Inspects target repo manifest files and installs missing toolchains just-in-time."""
        if not repo_dir or not Path(repo_dir).exists():
            return

        repo_path = Path(repo_dir)
        has = lambda name: (repo_path / name).exists()

        print(f"\n[EnvironmentBootstrapper] Checking toolchain requirements for {repo_path.name}...")

        # 1. Python tooling (Poetry / Flit / Pytest)
        is_poetry_project = has("poetry.lock")
        if not is_poetry_project and has("pyproject.toml"):
            try:
                content = (repo_path / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
                is_poetry_project = "[tool.poetry]" in content
            except Exception:
                is_poetry_project = False

        if is_poetry_project:
            if not shutil.which("poetry"):
                print("[Auto-Installer] Repository requires 'poetry'. Installing...")
                cmd = ["pip", "install", "poetry", "--break-system-packages"] if self.is_termux else [sys.executable, "-m", "pip", "install", "poetry"]
                self._run_cmd(cmd)

        if has("requirements.txt") or has("setup.py") or has("pyproject.toml"):
            import importlib.util
            if importlib.util.find_spec("pytest") is None and not shutil.which("pytest"):
                print("[Auto-Installer] Test suite requires 'pytest'. Installing...")
                cmd = ["pip", "install", "pytest", "--break-system-packages"] if self.is_termux else [sys.executable, "-m", "pip", "install", "pytest"]
                self._run_cmd(cmd)

        # 2. Node.js (pnpm / yarn)
        if has("package.json"):
            if has("pnpm-lock.yaml") and not shutil.which("pnpm"):
                print("[Auto-Installer] Repository requires 'pnpm'. Installing...")
                self._run_cmd(["npm", "install", "-g", "pnpm"])
            elif has("yarn.lock") and not shutil.which("yarn"):
                print("[Auto-Installer] Repository requires 'yarn'. Installing...")
                self._run_cmd(["npm", "install", "-g", "yarn"])

        # 3. Rust / Cargo
        if has("Cargo.toml") and not shutil.which("cargo"):
            print("[Auto-Installer] Rust manifest detected. Installing rust toolchain...")
            if self.is_termux:
                self._run_cmd(["pkg", "install", "rust", "-y"])

        # 4. C / C++ (Meson / Ninja / CMake)
        if has("meson.build") and not shutil.which("meson"):
            print("[Auto-Installer] Meson build file detected. Installing build tools...")
            if self.is_termux:
                self._run_cmd(["pkg", "install", "ninja", "-y"])
                self._run_cmd(["pip", "install", "meson", "--break-system-packages"])
            else:
                self._run_cmd([sys.executable, "-m", "pip", "install", "meson", "ninja"])

        if has("CMakeLists.txt") and not shutil.which("cmake"):
            print("[Auto-Installer] CMakeLists detected. Installing cmake...")
            if self.is_termux:
                self._run_cmd(["pkg", "install", "cmake", "-y"])

        print("[EnvironmentBootstrapper] Pre-flight toolchain check complete.")
