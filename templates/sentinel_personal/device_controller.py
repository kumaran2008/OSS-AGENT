import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from privacy_guard import StructuralPrivacyGuard
from system_auditor import SystemAuditor
from safety_scanner import SafetyScanner
from game_runner import GameRunner


class EphemeralPersonalAgent:
    """
    Zero-retention personal device agent with built-in hardware auditing,
    threat scanning, and autonomous game/dependency execution.
    """

    def __init__(self, adb_host: str = "127.0.0.1", adb_port: int = 5555):
        self.adb_target = f"{adb_host}:{adb_port}"
        self._session_context: List[Dict[str, str]] = []
        self._cached_dimensions: Optional[Tuple[int, int]] = None
        self.guard = StructuralPrivacyGuard()
        self.auditor = SystemAuditor(adb_target=self.adb_target)
        self.scanner = SafetyScanner()
        self.runner = GameRunner()

    def _run_adb(self, cmd: List[str]) -> subprocess.CompletedProcess:
        full_cmd = ["adb", "-s", self.adb_target] + cmd
        return subprocess.run(full_cmd, text=True, capture_output=True)

    def check_system_spec(self, target_app: Optional[str] = None) -> Dict[str, Any]:
        """Audits specs against target app requirements (e.g. freefire, mario)."""
        specs = self.auditor.get_hardware_specs()
        if target_app:
            compatible, reason = self.auditor.verify_app_compatibility(target_app)
            specs["target_app"] = target_app
            specs["compatible"] = compatible
            specs["assessment"] = reason
        return specs

    def audit_download(self, file_path: str) -> Dict[str, Any]:
        """Scans downloaded APK or file for security risks before opening/installing."""
        return self.scanner.audit_apk_file(Path(file_path))

    def setup_and_play_game(self, game_name: str, steps: int = 500) -> Dict[str, Any]:
        """Prepares dependencies and executes game sessions (e.g. mario)."""
        if "mario" in game_name.lower():
            return self.runner.launch_mario_session(steps=steps)
        return {"status": "FAILED", "error": f"Game engine for '{game_name}' not supported yet."}

    def unlock_device(self, pin: str) -> bool:
        self._run_adb(["shell", "input", "keyevent", "26"])
        self._run_adb(["shell", "input", "swipe", "500", "1500", "500", "500", "250"])
        self._run_adb(["shell", "input", "text", pin])
        self._run_adb(["shell", "input", "keyevent", "66"])
        return True

    def launch_app(self, package_name: str, activity_name: Optional[str] = None) -> bool:
        if activity_name:
            cmd = ["shell", "am", "start", "-n", f"{package_name}/{activity_name}"]
        else:
            cmd = ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
        return self._run_adb(cmd).returncode == 0

    def get_screen_elements(self) -> List[Dict[str, Any]]:
        dump_path = "/sdcard/window_dump.xml"
        self._run_adb(["shell", "uiautomator", "dump", dump_path])
        cat_res = self._run_adb(["shell", "cat", dump_path])
        self._run_adb(["shell", "rm", "-f", dump_path])
        return self.guard.filter_ui_hierarchy(cat_res.stdout)

    def tap_coordinates(self, x: int, y: int) -> bool:
        return self._run_adb(["shell", "input", "tap", str(x), str(y)]).returncode == 0

    def get_unread_notifications(self) -> List[Dict[str, Any]]:
        res = subprocess.run(["termux-notification-list"], capture_output=True, text=True)
        if res.returncode != 0 or not res.stdout.strip():
            return []
        try:
            return self.guard.filter_notifications(json.loads(res.stdout))
        except Exception:
            return []

    def clear_memory(self):
        self._session_context.clear()
