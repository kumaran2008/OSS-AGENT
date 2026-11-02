import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from tools.dashboard import dashboard


@dataclass
class MissingDependency:
    component: str          # e.g. "pytest module"
    reason: str             # human-readable explanation
    install_command: str    # exact copy-pasteable fix


@dataclass
class SecurityFinding:
    severity: str           # "HIGH", "CRITICAL", "MEDIUM"
    file_path: str
    line_number: int
    rule: str
    snippet: str


@dataclass
class GuardResult:
    ok: bool
    repo_name: str
    missing: List[MissingDependency] = field(default_factory=list)
    security_findings: List[SecurityFinding] = field(default_factory=list)


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


class SecurityAgent:
    """
    Audits codebase changes for secret exposure, credential leakage,
    eval execution, and injection vulnerabilities.
    """

    SECRET_PATTERNS = [
        ("CRITICAL", "OpenAI / OpenRouter API Key", re.compile(r"sk-[a-zA-Z0-9_-]{24,}")),
        ("CRITICAL", "GitHub Personal Access Token", re.compile(r"ghp_[a-zA-Z0-9]{36}")),
        ("CRITICAL", "Generic Secret Token", re.compile(r"""(?:api_key|token|secret|password)\s*[:=]\s*['"][a-zA-Z0-9_\-]{16,}['"]""", re.IGNORECASE)),
        ("HIGH", "Private Key Header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
        ("HIGH", "Insecure Dynamic Execution", re.compile(r"""\b(?:eval|exec)\s*\((?![^)]*(?:True|False|None))\s*[^)]+\)""")),
        ("MEDIUM", "Shell Injection Risk", re.compile(r"""os\.system\s*\(\s*f['"]|subprocess\.(?:Popen|call|run)\s*\([^)]*shell\s*=\s*True""")),
    ]

    def scan_path(self, target_dir: Path) -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        skip_dirs = {".git", "node_modules", "venv", "__pycache__", ".venv"}

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix in [".py", ".js", ".jsx", ".ts", ".tsx", ".env", ".json", ".yml", ".yaml"]:
                    try:
                        content = file_path.read_text(errors="ignore")
                        lines = content.splitlines()
                        for i, line in enumerate(lines, 1):
                            for sev, rule, pattern in self.SECRET_PATTERNS:
                                if pattern.search(line):
                                    findings.append(SecurityFinding(
                                        severity=sev,
                                        file_path=str(file_path.relative_to(target_dir)),
                                        line_number=i,
                                        rule=rule,
                                        snippet=line.strip()[:80],
                                    ))
                    except Exception:
                        continue
        return findings


class RepoGuard:
    """
    Pre-flight inspector and active security auditor.
    Validates environment binaries, package declarations, and code security.
    """

    def __init__(self):
        self.platform = _detect_platform()
        self.security_agent = SecurityAgent()

    def inspect_workspace(self, repo_path: Path) -> GuardResult:
        repo_name = repo_path.name
        missing: List[MissingDependency] = []

        has = lambda fname: (repo_path / fname).exists()

        # Python projects
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

        # tox
        if has("tox.ini") and importlib.util.find_spec("tox") is None:
            missing.append(MissingDependency(
                component="tox",
                reason="tox.ini found but the 'tox' package is not installed.",
                install_command=_install_cmd("tox", self.platform, pip_fallback="pip install tox"),
            ))

        # Node projects
        if has("package.json"):
            from tools.tests import detect_node_package_manager, resolve_package_manager_command
            manager = detect_node_package_manager(repo_path)
            install_cmd = resolve_package_manager_command(repo_path)

            if install_cmd is None:
                missing.append(MissingDependency(
                    component=manager or "npm",
                    reason=f"package.json found (detected package manager: {manager}) but no execution binary found.",
                    install_command=_install_cmd(manager or "npm", self.platform),
                ))
            elif not (repo_path / "node_modules").exists():
                missing.append(MissingDependency(
                    component="node_modules",
                    reason=f"package.json found (detected package manager: {manager}) but dependencies not installed.",
                    install_command=f"cd {repo_path} && {install_cmd}",
                ))

        # Rust projects
        if has("Cargo.toml") and not shutil.which("cargo"):
            missing.append(MissingDependency(
                component="cargo",
                reason="Cargo.toml found but the Rust toolchain (cargo) is not installed on this host.",
                install_command=_install_cmd("cargo", self.platform),
            ))

        # C/C++ projects
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

        # Makefile
        if has("Makefile") and not shutil.which("make"):
            missing.append(MissingDependency(
                component="make",
                reason="Makefile found but 'make' is not available on this host.",
                install_command=_install_cmd("make", self.platform),
            ))

        # Security check run
        security_findings = self.security_agent.scan_path(repo_path)
        if security_findings:
            dashboard.emit("LOG_STREAM", {"message": f"Security Guard flagged {len(security_findings)} warning(s)."})

        is_ok = len(missing) == 0 and not any(f.severity == "CRITICAL" for f in security_findings)
        return GuardResult(
            ok=is_ok,
            repo_name=repo_name,
            missing=missing,
            security_findings=security_findings
        )

    def _check_requirements_installed(self, requirements_path: Path) -> List[str]:
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
        "[SECURITY & ENVIRONMENT GUARD REPORT]",
        "=" * 60,
        f"Repository: {result.repo_name}",
        "",
    ]
    if result.missing:
        lines.append("--- MISSING HOST DEPENDENCIES ---")
        for i, dep in enumerate(result.missing, 1):
            lines.append(f"#{i}: {dep.component}")
            lines.append(f"  Reason: {dep.reason}")
            lines.append(f"  Fix:    {dep.install_command}")
            lines.append("")

    if result.security_findings:
        lines.append("--- SECURITY FINDINGS ---")
        for f in result.security_findings:
            lines.append(f"[{f.severity}] {f.rule} in {f.file_path}:{f.line_number}")
            lines.append(f"  Code: {f.snippet}")
            lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
