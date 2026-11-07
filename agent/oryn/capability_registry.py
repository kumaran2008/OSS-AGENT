from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.kernel.fault_recorder import fault_recorder
from agent.oryn.contracts import ChannelType


@dataclass(slots=True)
class ApplicationCapability:
    app_id: str
    display_name: str
    supported_channels: List[ChannelType]
    cli_binary: Optional[str] = None
    cli_help_flags: List[str] = field(default_factory=list)
    cdp_port: Optional[int] = None
    mcp_server_id: Optional[str] = None
    python_libraries: List[str] = field(default_factory=list)
    com_prog_id: Optional[str] = None
    uia_window_class: Optional[str] = None
    channel_confidences: Dict[str, float] = field(default_factory=dict)
    last_probed_at: float = field(default_factory=time.time)

    def preferred_channel(self) -> Tuple[ChannelType, float]:
        priority_order: List[ChannelType] = [
            "native_api",
            "dom",
            "cdp",
            "accessibility",
            "vision",
            "frontier_cua",
        ]
        best_ch: ChannelType = "frontier_cua"
        best_conf = 0.0
        for ch in priority_order:
            if ch in self.supported_channels:
                conf = self.channel_confidences.get(ch, 0.75)
                if conf >= 0.85:
                    return ch, conf
                if conf > best_conf:
                    best_ch = ch
                    best_conf = conf
        return best_ch, max(best_conf, 0.60)


class ORYNApplicationCapabilityRegistry:
    """Runtime Application Capability Prober & Discovery Registry for ORYN."""

    DB_PATH = Path("workspace/kernel_governance.db")

    KNOWN_APP_SPECS: Dict[str, Dict[str, Any]] = {
        "excel": {
            "display_name": "Spreadsheet / Microsoft Excel / LibreOffice Calc",
            "cli_candidates": ["libreoffice", "soffice", "gnumeric"],
            "python_libs": ["openpyxl", "pandas", "csv", "sqlite3"],
            "com_prog_id": "Excel.Application",
            "uia_class": "XLMAIN",
        },
        "word": {
            "display_name": "Document Processor / Microsoft Word / LibreOffice Writer",
            "cli_candidates": ["libreoffice", "pandoc", "pdflatex"],
            "python_libs": ["docx", "reportlab"],
            "com_prog_id": "Word.Application",
            "uia_class": "OpusApp",
        },
        "browser": {
            "display_name": "Chromium / Chrome / Edge / Brave / Termux Web Browser",
            "cli_candidates": [
                "google-chrome",
                "chromium",
                "chromium-browser",
                "microsoft-edge",
                "brave-browser",
                "termux-open-url",
            ],
            "cdp_ports": [9222, 9223, 9333],
            "python_libs": ["urllib.request", "html.parser"],
        },
        "vscode": {
            "display_name": "Visual Studio Code (Electron IDE)",
            "cli_candidates": ["code", "codium"],
            "cdp_ports": [9222, 9229],
            "python_libs": ["ast", "py_compile"],
            "uia_class": "Chrome_WidgetWin_1",
        },
        "calculator": {
            "display_name": "Calculator / Math Engine",
            "cli_candidates": ["bc", "python3", "qalc"],
            "python_libs": ["math", "decimal", "statistics"],
            "uia_class": "ApplicationFrameWindow",
        },
        "git": {
            "display_name": "Git & GitHub Version Control",
            "cli_candidates": ["git", "gh"],
            "python_libs": ["subprocess", "difflib"],
        },
        "obs": {
            "display_name": "OBS Studio Broadcast Engine",
            "cli_candidates": ["obs"],
            "cdp_ports": [4455],
            "python_libs": ["asyncio", "json"],
        },
    }

    def __init__(self) -> None:
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, ApplicationCapability] = {}
        self.os_name = platform.system().lower()
        self.is_termux = os.path.exists("/data/data/com.termux") or "TERMUX_VERSION" in os.environ
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oryn_app_capabilities (
                    app_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    supported_channels_json TEXT NOT NULL,
                    cli_binary TEXT,
                    cdp_port INTEGER,
                    python_libraries_json TEXT NOT NULL,
                    channel_confidences_json TEXT NOT NULL,
                    last_probed_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def is_tcp_port_open(host: str, port: int, timeout: float = 0.08) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def _has_python_lib(mod_name: str) -> bool:
        try:
            return importlib.util.find_spec(mod_name.split(".")[0]) is not None
        except Exception:
            return False

    def _probe_accessibility_support(self) -> Tuple[bool, float]:
        if self.is_termux:
            has_uia = shutil.which("uiautomator") is not None
            return True, (0.92 if has_uia else 0.78)
        if self.os_name == "windows":
            return True, 0.95
        if self.os_name == "darwin":
            return True, 0.93
        if self.os_name == "linux":
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            has_tools = any(shutil.which(b) for b in ("xdotool", "wmctrl", "gdbus")) or self._has_python_lib("gi")
            return (has_display or has_tools), (0.90 if (has_display and has_tools) else 0.75)
        return False, 0.0

    @fault_recorder.guard(subsystem="oryn.capability_registry")
    def probe_application(self, app_name_or_task: str, force_refresh: bool = False) -> ApplicationCapability:
        key = app_name_or_task.strip().lower()
        for known_id in self.KNOWN_APP_SPECS:
            if known_id in key:
                key = known_id
                break
        if key in ("chrome", "edge", "brave", "firefox", "web", "website", "url", "http"):
            key = "browser"
        elif key in ("spreadsheet", "xlsx", "csv", "calc"):
            key = "excel"

        if not force_refresh and key in self._cache and (time.time() - self._cache[key].last_probed_at) < 120.0:
            return self._cache[key]

        spec = self.KNOWN_APP_SPECS.get(
            key,
            {
                "display_name": app_name_or_task.strip(),
                "cli_candidates": [key.split()[0]] if key else [],
                "cdp_ports": [9222],
                "python_libs": [],
            },
        )

        channels: List[ChannelType] = []
        confidences: Dict[str, float] = {}

        found_cli: Optional[str] = None
        for cand in spec.get("cli_candidates", []):
            path = shutil.which(cand)
            if path:
                found_cli = path
                break

        avail_py_libs = [lib for lib in spec.get("python_libs", []) if self._has_python_lib(lib)]
        com_prog = spec.get("com_prog_id") if self.os_name == "windows" and self._has_python_lib("win32com") else None

        if found_cli or avail_py_libs or com_prog:
            channels.append("native_api")
            confidences["native_api"] = 0.99 if (avail_py_libs or com_prog) else 0.95

        open_cdp_port: Optional[int] = None
        for port in spec.get("cdp_ports", []):
            if self.is_tcp_port_open("127.0.0.1", port):
                open_cdp_port = port
                break

        if key == "browser" or open_cdp_port is not None or found_cli is not None:
            if key in ("browser", "vscode") or open_cdp_port is not None:
                channels.extend(["dom", "cdp"])
                confidences["dom"] = 0.96 if open_cdp_port else 0.91
                confidences["cdp"] = 0.97 if open_cdp_port else 0.90

        ax_ok, ax_conf = self._probe_accessibility_support()
        if ax_ok:
            channels.append("accessibility")
            confidences["accessibility"] = ax_conf

        channels.extend(["vision", "frontier_cua"])
        confidences["vision"] = 0.88
        confidences["frontier_cua"] = 0.94

        help_flags: List[str] = []
        if found_cli and key not in ("browser", "obs"):
            try:
                res = subprocess.run(
                    [found_cli, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=1.2,
                )
                out = (res.stdout or "") + (res.stderr or "")
                for line in out.splitlines()[:40]:
                    s = line.strip()
                    if s.startswith("-"):
                        help_flags.append(s[:80])
            except Exception:
                pass

        cap = ApplicationCapability(
            app_id=key,
            display_name=spec.get("display_name", key),
            supported_channels=channels,
            cli_binary=found_cli,
            cli_help_flags=help_flags[:12],
            cdp_port=open_cdp_port,
            python_libraries=avail_py_libs,
            com_prog_id=com_prog,
            uia_window_class=spec.get("uia_class"),
            channel_confidences=confidences,
            last_probed_at=time.time(),
        )
        self._cache[key] = cap
        self._persist_capability(cap)
        return cap

    def _persist_capability(self, cap: ApplicationCapability) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO oryn_app_capabilities (
                    app_id, display_name, supported_channels_json, cli_binary,
                    cdp_port, python_libraries_json, channel_confidences_json, last_probed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cap.app_id,
                    cap.display_name,
                    json.dumps(cap.supported_channels),
                    cap.cli_binary,
                    cap.cdp_port,
                    json.dumps(cap.python_libraries),
                    json.dumps(cap.channel_confidences),
                    cap.last_probed_at,
                ),
            )
            conn.commit()

    def select_optimal_channel(
        self,
        task_description: str,
        target_app: str = "workstation",
        require_visual: bool = False,
    ) -> Dict[str, Any]:
        cap = self.probe_application(target_app if target_app != "workstation" else task_description)
        if require_visual:
            chosen: ChannelType = "vision"
            conf = cap.channel_confidences.get("vision", 0.88)
        else:
            chosen, conf = cap.preferred_channel()

        return {
            "app_id": cap.app_id,
            "display_name": cap.display_name,
            "selected_channel": chosen,
            "confidence": conf,
            "supported_channels": cap.supported_channels,
            "cli_binary": cap.cli_binary,
            "cdp_port": cap.cdp_port,
            "python_libraries": cap.python_libraries,
            "channel_confidences": cap.channel_confidences,
        }


oryn_capability_registry = ORYNApplicationCapabilityRegistry()
