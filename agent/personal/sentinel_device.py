import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from agent.personal.privacy_guard import StructuralPrivacyGuard


class EphemeralPersonalAgent:
    """
    Zero-retention personal intelligence agent for local device automation.
    Enforces adaptive viewport bounds and structural allow-listing privacy.
    """

    def __init__(self, adb_host: str = "127.0.0.1", adb_port: int = 5555):
        self.adb_target = f"{adb_host}:{adb_port}"
        self._session_context: List[Dict[str, str]] = []
        self._cached_dimensions: Optional[Tuple[int, int]] = None
        self.guard = StructuralPrivacyGuard()

    def _run_adb(self, cmd: List[str]) -> subprocess.CompletedProcess:
        """Executes an ADB command targeting the connected device."""
        full_cmd = ["adb", "-s", self.adb_target] + cmd
        return subprocess.run(full_cmd, text=True, capture_output=True)

    def get_screen_dimensions(self) -> Tuple[int, int]:
        """Queries physical display resolution via wm size."""
        if self._cached_dimensions:
            return self._cached_dimensions

        res = self._run_adb(["shell", "wm", "size"])
        matches = re.findall(r"size:\s*(\d+)x(\d+)", res.stdout)
        if matches:
            w, h = int(matches[-1][0]), int(matches[-1][1])
            self._cached_dimensions = (w, h)
            return self._cached_dimensions
        return (1080, 2400)

    def unlock_device(self, pin: str) -> bool:
        """Wakes screen and performs adaptive vertical swipe unlock."""
        w, h = self.get_screen_dimensions()
        self._run_adb(["shell", "input", "keyevent", "26"])
        
        center_x = w // 2
        start_y = int(h * 0.80)
        end_y = int(h * 0.25)
        self._run_adb(["shell", "input", "swipe", str(center_x), str(start_y), str(center_x), str(end_y), "250"])

        res = self._run_adb(["shell", "input", "text", pin])
        self._run_adb(["shell", "input", "keyevent", "66"])
        return res.returncode == 0

    def launch_app(self, package_name: str, activity_name: Optional[str] = None) -> bool:
        """Launches application by package name."""
        if activity_name:
            target = f"{package_name}/{activity_name}"
            cmd = ["shell", "am", "start", "-n", target]
        else:
            cmd = ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
        res = self._run_adb(cmd)
        return res.returncode == 0

    def get_screen_elements(self) -> List[Dict[str, Any]]:
        """Dumps UI hierarchy and returns structurally sanitized interactive nodes."""
        dump_path = "/sdcard/window_dump.xml"
        self._run_adb(["shell", "uiautomator", "dump", dump_path])
        cat_res = self._run_adb(["shell", "cat", dump_path])
        self._run_adb(["shell", "rm", "-f", dump_path])
        return self.guard.filter_ui_hierarchy(cat_res.stdout)

    def tap_coordinates(self, x: int, y: int) -> bool:
        """Executes simulated touch at absolute pixel (x, y)."""
        res = self._run_adb(["shell", "input", "tap", str(x), str(y)])
        return res.returncode == 0

    def tap_element_by_control(self, control_label: str) -> bool:
        """Taps an on-screen interactive control by its validated label."""
        elements = self.get_screen_elements()
        for el in elements:
            if el.get("control_label", "").lower() == control_label.lower() and el.get("center"):
                coords = el["center"]
                return self.tap_coordinates(coords["x"], coords["y"])
        return False

    def get_unread_notifications(self) -> List[Dict[str, Any]]:
        """Extracts device notifications filtered by structural allow-list."""
        termux_api = subprocess.run(["termux-notification-list"], capture_output=True, text=True)
        if termux_api.returncode != 0 or not termux_api.stdout.strip():
            return []
        try:
            raw_notes = json.loads(termux_api.stdout)
            return self.guard.filter_notifications(raw_notes, allow_content=False)
        except Exception:
            return []

    def clear_memory(self):
        """Purges ephemeral memory cache."""
        self._session_context.clear()
