from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Dict, Optional, Tuple

from agent.kernel.fault_recorder import fault_recorder


@dataclass(slots=True)
class RuntimeEnvironmentConfig:
    runtime_id: str
    runtime_type: str
    is_mobile: bool
    workspace_dir: Path
    display_dimensions: Tuple[int, int] = (1024, 768)
    allow_network: bool = True
    active_process_count: int = 0


class ORYNRuntimeManager:
    """Manages execution runtimes, per-desktop session mutex locks, and screen capture."""

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.os_name = platform.system().lower()
        self.is_termux = os.path.exists("/data/data/com.termux") or "TERMUX_VERSION" in os.environ
        self._desktop_mutex = asyncio.Lock()
        self._active_runtimes: Dict[str, RuntimeEnvironmentConfig] = {}
        self._init_default_runtime()

    def _init_default_runtime(self) -> None:
        rid = "termux_mobile" if self.is_termux else f"local_{self.os_name}"
        width, height = self._detect_display_dimensions()
        cfg = RuntimeEnvironmentConfig(
            runtime_id=rid,
            runtime_type="android_termux" if self.is_termux else "local_workstation",
            is_mobile=self.is_termux,
            workspace_dir=self.workspace_root,
            display_dimensions=(width, height),
            allow_network=True,
        )
        self._active_runtimes[rid] = cfg

    def _detect_display_dimensions(self) -> Tuple[int, int]:
        if self.is_termux:
            if shutil.which("wm"):
                try:
                    out = subprocess.check_output(
                        ["wm", "size"],
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=1.0,
                    )
                    for part in out.split():
                        if "x" in part:
                            w_s, h_s = part.strip().split("x", 1)
                            if w_s.isdigit() and h_s.isdigit():
                                return int(w_s), int(h_s)
                except Exception:
                    pass
            return (1080, 2400)

        if shutil.which("xdpyinfo"):
            try:
                out = subprocess.check_output(
                    ["xdpyinfo"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.5,
                )
                for line in out.splitlines():
                    if "dimensions:" in line:
                        dim_part = line.split("dimensions:")[1].strip().split()[0]
                        w_s, h_s = dim_part.split("x", 1)
                        return int(w_s), int(h_s)
            except Exception:
                pass
        return (1920, 1080)

    @property
    def primary_runtime(self) -> RuntimeEnvironmentConfig:
        return next(iter(self._active_runtimes.values()))

    @fault_recorder.guard(subsystem="oryn.runtime")
    async def acquire_desktop_lock(self, timeout_sec: float = 5.0) -> bool:
        try:
            await asyncio.wait_for(self._desktop_mutex.acquire(), timeout=timeout_sec)
            return True
        except asyncio.TimeoutError:
            return False

    def release_desktop_lock(self) -> None:
        if self._desktop_mutex.locked():
            self._desktop_mutex.release()

    @contextlib.asynccontextmanager
    async def desktop_session_lock(self, timeout_sec: float = 5.0) -> AsyncIterator[bool]:
        acquired = await self.acquire_desktop_lock(timeout_sec=timeout_sec)
        try:
            yield acquired
        finally:
            if acquired:
                self.release_desktop_lock()

    def capture_fullscreen(self, output_path: Optional[Path] = None) -> Optional[Path]:
        target = output_path or (self.workspace_root / "workspace/screen_capture.png")
        target.parent.mkdir(parents=True, exist_ok=True)

        if self.is_termux:
            for cmd in (["screencap", "-p", str(target)], ["termux-screenshot", str(target)]):
                if shutil.which(cmd[0]):
                    try:
                        subprocess.run(
                            cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3.0,
                        )
                        if target.exists() and target.stat().st_size > 100:
                            return target
                    except Exception:
                        pass
            return None

        for tool, args in (
            ("scrot", [str(target)]),
            ("maim", [str(target)]),
            ("import", ["-window", "root", str(target)]),
            ("screencapture", ["-x", str(target)]),
        ):
            if shutil.which(tool):
                try:
                    subprocess.run(
                        [tool, *args],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2.5,
                    )
                    if target.exists() and target.stat().st_size > 100:
                        return target
                except Exception:
                    pass
        return None


oryn_runtime = ORYNRuntimeManager()
