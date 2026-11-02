from __future__ import annotations
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from typing import Dict, List, Any
import psutil

@dataclass
class SystemTopology:
    os_name: str
    os_release: str
    architecture: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_gb: float
    ram_available_gb: float
    has_microphone: bool
    has_display: bool
    installed_browsers: List[str]
    installed_tools: List[str]

class SystemAdapter:
    """Probes the host operating system, hardware, and audio/display availability."""

    @staticmethod
    def inspect() -> SystemTopology:
        ram = psutil.virtual_memory()
        
        # Detect available web browsers
        browsers = []
        for b in ["google-chrome", "chrome", "chromium", "brave-browser", "firefox", "msedge"]:
            if shutil.which(b):
                browsers.append(b)

        # Detect CLI utilities
        cli_tools = []
        for tool in ["git", "curl", "ffmpeg", "node", "npm", "docker"]:
            if shutil.which(tool):
                cli_tools.append(tool)

        # Check display environment
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or platform.system() in ["Windows", "Darwin"])

        # Check audio input availability
        has_mic = False
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            has_mic = any(d.get("max_input_channels", 0) > 0 for d in devices)
        except Exception:
            has_mic = False

        return SystemTopology(
            os_name=platform.system(),
            os_release=platform.release(),
            architecture=platform.machine(),
            cpu_cores_physical=psutil.cpu_count(logical=False) or 1,
            cpu_cores_logical=psutil.cpu_count(logical=True) or 1,
            ram_total_gb=round(ram.total / (1024 ** 3), 2),
            ram_available_gb=round(ram.available / (1024 ** 3), 2),
            has_microphone=has_mic,
            has_display=has_display,
            installed_browsers=browsers,
            installed_tools=cli_tools,
        )
