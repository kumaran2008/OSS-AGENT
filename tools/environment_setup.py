import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List


@dataclass
class ToolStatus:
    name: str
    installed: bool
    install_command: str
    requires_confirmation: bool = False


def _detect_platform() -> str:
    import os
    if "com.termux" in os.environ.get("PREFIX", ""):
        return "termux"
    if platform.system().lower() == "darwin":
        return "mac"
    if platform.system().lower().startswith("linux"):
        return "linux"
    if platform.system().lower().startswith("win"):
        return "windows"
    return "unknown"


class EnvironmentBootstrapper:
    """
    Detects and automatically installs missing dev tools (Node package
    managers, Python tooling, C/C++ build tools) via official package
    registries (pip/npm/apt/pkg/brew) with no confirmation needed —
    these are standard, checksum-verified installs.

    Exception: Ollama's install script is a curl-pipe-to-shell command
    (downloads and executes an arbitrary remote script). This one
    pattern is explicitly blocked elsewhere in this project
    (tools/shell.py's DANGEROUS_PATTERNS) as a known supply-chain risk,
    so it stays a single one-time confirmation here too — everything
    else installs silently.

    Bun is never auto-installed or suggested on Termux — it does not
    officially support Android, and its native binary reliably fails
    post-install on that platform even when the JS wrapper appears to
    install successfully.
    """

    def __init__(self):
        self.platform = _detect_platform()

    def _cmd(self, termux: str, mac: str, linux: str, windows: str = None) -> str:
        return {
            "termux": termux, "mac": mac, "linux": linux, "windows": windows or "",
        }.get(self.platform, "")

    def _run(self, command: str) -> bool:
        if not command:
            return False
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=180)
            return result.returncode == 0
        except Exception:
            return False

    def _collect_checks(self) -> List[ToolStatus]:
        pip_suffix = " --break-system-packages" if self.platform == "termux" else ""
        checks = []

        node_tools = ("pnpm", "yarn") if self.platform == "termux" else ("pnpm", "yarn", "bun")
        for tool in node_tools:
            checks.append(ToolStatus(tool, shutil.which(tool) is not None, f"npm install -g {tool}"))

        for tool in ("pytest", "flake8", "poetry", "uv"):
            checks.append(ToolStatus(tool, shutil.which(tool) is not None, f"pip install {tool}{pip_suffix}"))

        for tool in ("cmake", "ninja", "meson", "cppcheck"):
            checks.append(ToolStatus(tool, shutil.which(tool) is not None, self._cmd(
                f"pkg install {tool} -y", f"brew install {tool}", f"sudo apt install {tool} -y",
            )))

        if self.platform != "termux":
            checks.append(ToolStatus(
                "ollama", shutil.which("ollama") is not None,
                self._cmd("", "brew install ollama", "curl -fsSL https://ollama.com/install.sh | sh"),
                requires_confirmation=True,
            ))

        return checks

    def bootstrap_environment(self) -> None:
        """Installs every missing tool automatically, except Ollama
        (single confirmation, since it's a curl-pipe-to-shell install)."""
        missing = [t for t in self._collect_checks() if not t.installed and t.install_command]
        if not missing:
            return

        print(f"\n[Auto-Installer] {len(missing)} missing dev tool(s) detected.")
        for tool in missing:
            if tool.requires_confirmation:
                print(f"\n[Auto-Installer] '{tool.name}' requires running a script downloaded "
                      f"from the internet:\n  {tool.install_command}")
                confirm = input("Run this now? [y/N]: ").strip().lower()
                if confirm != "y":
                    print(f"[Auto-Installer] Skipped '{tool.name}'.")
                    continue

            print(f"[Auto-Installer] Missing '{tool.name}' detected. Auto-installing...")
            ok = self._run(tool.install_command)
            print(f"[Auto-Installer] '{tool.name}' " + ("installed successfully." if ok else "install failed — continuing anyway."))
