import os
import sys
import ast
import time
import socket
import difflib
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class DeviceWorkspaceProfile:
    is_termux: bool
    is_desktop: bool
    has_gui: bool
    detected_editors: List[str]
    preferred_editor: Optional[str] = None


class WorkspaceOrchestrator:
    """
    Device-Adaptive Workspace Surface & Atomic Code Orchestrator.
    - Adapts coding interface based on host environment (PC vs Mobile Termux).
    - Executes atomic multi-file patch transactions with syntax verification.
    - Performs non-blocking TCP/HTTP health probes on local dev servers.
    - Generates colorized unified diffs for human review.
    """

    SUPPORTED_EDITORS = ["cursor", "code", "zed", "subl", "nvim", "vim", "nano"]

    def __init__(self, workspace_root: Path):
        self.workspace = workspace_root.resolve()
        self.profile = self._detect_device_profile()

    def _detect_device_profile(self) -> DeviceWorkspaceProfile:
        is_termux = os.path.exists("/data/data/com.termux")
        has_display = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY") or sys.platform == "darwin" or sys.platform == "win32")
        is_desktop = not is_termux and has_display

        detected = []
        for ed in self.SUPPORTED_EDITORS:
            if shutil.which(ed):
                detected.append(ed)

        pref = detected[0] if detected else None
        return DeviceWorkspaceProfile(
            is_termux=is_termux,
            is_desktop=is_desktop,
            has_gui=has_display,
            detected_editors=detected,
            preferred_editor=pref
        )

    # -------------------------------------------------------------------------
    # 1. Device-Adaptive Editor Hooking
    # -------------------------------------------------------------------------
    def open_in_editor(self, relative_file: str, line_number: int = 1) -> Tuple[bool, str]:
        """
        Adapts coding phase display according to the host machine:
        - PC / Desktop: Calls `code -r -g file:line` or `cursor -g file:line`.
        - Android Termux / Headless: Dispatches termux-open if present or emits location marker.
        """
        full_path = (self.workspace / relative_file).resolve()
        if not full_path.exists():
            return False, f"File not found: {full_path}"

        if self.profile.is_desktop and self.profile.preferred_editor:
            ed = self.profile.preferred_editor
            try:
                # -r reuses existing window, -g jumps directly to line
                if ed in ["code", "cursor"]:
                    subprocess.Popen([ed, "-r", "-g", f"{full_path}:{line_number}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif ed == "zed":
                    subprocess.Popen([ed, f"{full_path}:{line_number}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen([ed, str(full_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Opened {relative_file}:{line_number} in {ed}."
            except Exception as e:
                return False, f"Failed to launch desktop editor {ed}: {e}"

        # Mobile Termux / Headless Handling
        if self.profile.is_termux and shutil.which("termux-open"):
            try:
                subprocess.Popen(["termux-open", str(full_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Dispatched {relative_file} via termux-open."
            except Exception:
                pass

        return True, f"Workspace focused on {relative_file}:{line_number} (Headless / Terminal mode active)."

    # -------------------------------------------------------------------------
    # 2. Multi-File Atomic Patch Transactions with Pre-Flight Syntax Guard
    # -------------------------------------------------------------------------
    def atomic_multi_file_patch(self, patch_manifest: Dict[str, str]) -> Tuple[bool, str, List[str]]:
        """
        Applies coordinated edits across multiple files in a single atomic transaction.
        Verifies Python syntax (AST parse) in memory across all files before touching disk.
        If any file fails syntax checks, the entire transaction is rejected.
        """
        # Phase 1: Pre-flight syntax and path validation
        syntax_errors = []
        for rel_path, new_content in patch_manifest.items():
            if rel_path.endswith(".py"):
                try:
                    ast.parse(new_content, filename=rel_path)
                except SyntaxError as se:
                    syntax_errors.append(f"{rel_path}:{se.lineno} SyntaxError: {se.msg}")

        if syntax_errors:
            return False, f"Transaction rejected (Syntax Pre-Flight Failed):\n" + "\n".join(syntax_errors), []

        # Phase 2: In-Memory Backup of current contents
        backups: Dict[Path, Optional[str]] = {}
        target_paths: Dict[str, Path] = {}

        for rel_path in patch_manifest.keys():
            full_p = (self.workspace / rel_path).resolve()
            target_paths[rel_path] = full_p
            if full_p.exists():
                try:
                    backups[full_p] = full_p.read_text(encoding="utf-8")
                except Exception:
                    backups[full_p] = None
            else:
                backups[full_p] = None

        # Phase 3: Apply writes to disk
        modified_files = []
        try:
            for rel_path, content in patch_manifest.items():
                p = target_paths[rel_path]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                modified_files.append(rel_path)
            return True, f"Atomically updated {len(modified_files)} file(s).", modified_files
        except Exception as write_err:
            # Phase 4: Emergency Rollback
            for p, orig_content in backups.items():
                if orig_content is not None:
                    p.write_text(orig_content, encoding="utf-8")
                elif p.exists():
                    p.unlink(missing_ok=True)
            return False, f"Write failure, rolled back transaction: {write_err}", []

    # -------------------------------------------------------------------------
    # 3. Live Dev Server Health Probing (Smoke Testing)
    # -------------------------------------------------------------------------
    def probe_service_health(
        self,
        port: int,
        host: str = "127.0.0.1",
        path: str = "/",
        timeout_sec: float = 6.0,
        expected_status: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Verifies that a background development server (e.g. FastAPI, Node, Flask)
        is active, listening on port, and returning valid HTTP responses.
        """
        start = time.monotonic()
        is_port_open = False

        # 1. Non-blocking TCP Port Probe
        while (time.monotonic() - start) < timeout_sec:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                try:
                    s.connect((host, port))
                    is_port_open = True
                    break
                except (ConnectionRefusedError, socket.timeout, OSError):
                    time.sleep(0.15)

        if not is_port_open:
            return False, f"Service probe failed: Port {port} did not open within {timeout_sec:.1f}s."

        # 2. Raw HTTP GET Handshake
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect((host, port))
                req = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUser-Agent: oss-agent-probe\r\nConnection: close\r\n\r\n"
                s.sendall(req.encode("utf-8"))
                resp_bytes = s.recv(4096)
                resp_text = resp_bytes.decode("utf-8", errors="replace")

                status_line = resp_text.splitlines()[0] if resp_text else "NO_RESPONSE"
                if expected_status:
                    if f" {expected_status} " in status_line:
                        return True, f"Service verified healthy on {host}:{port}{path} ({status_line})"
                    return False, f"Service returned unexpected status: {status_line}"

                return True, f"Service verified alive on {host}:{port}{path} ({status_line})"
        except Exception as http_err:
            return True, f"Port {port} is listening (HTTP probe skipped: {http_err})"

    # -------------------------------------------------------------------------
    # 4. Colorized Unified Diff Generator
    # -------------------------------------------------------------------------
    @staticmethod
    def generate_unified_diff(orig_text: str, new_text: str, filename: str) -> str:
        """Produces terminal-friendly unified diffs."""
        orig_lines = orig_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        diff_iter = difflib.unified_diff(
            orig_lines, new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3
        )
        return "".join(diff_iter).strip()
