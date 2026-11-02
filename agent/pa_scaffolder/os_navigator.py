import os
import sys
import time
import shutil
import platform
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

from agent.pa_scaffolder.app_layout_cache import AppLayoutCache


@dataclass
class UIElement:
    name: str
    bounds: Tuple[int, int, int, int]
    center: Tuple[int, int]


@dataclass
class DeviceEnvironment:
    os_family: str                      # "android", "linux", "darwin", "windows"
    is_android: bool = False
    has_root: bool = False              # Android su
    has_rish: bool = False              # Shizuku / Rish
    has_adb: bool = False               # Local ADB paired and active
    has_termux_api: bool = False
    display_server: str = "none"
    input_driver: str = "simulated"     # "su_input", "rish_input", "adb_input", "termux_input", "xdotool", "osascript", "simulated"
    screen_width: int = 1080
    screen_height: int = 2400
    permission_note: str = ""


class OSNavigator:
    """
    Adaptive Cross-Platform Operating System Interaction Engine.
    Dynamically tests touch injection permissions and switches execution
    paths between Root, Shizuku, Local ADB, and graceful simulation.
    """

    ANDROID_PACKAGES: Dict[str, str] = {
        "youtube": "com.google.android.youtube",
        "chrome": "com.android.chrome",
        "settings": "com.android.settings",
        "camera": "com.android.camera2",
        "whatsapp": "com.whatsapp",
        "instagram": "com.instagram.android",
        "twitter": "com.twitter.android",
        "x": "com.twitter.android",
        "spotify": "com.spotify.music",
        "piano": "com.gamestar.perfectpiano",
        "keyboard": "com.gamestar.perfectpiano"
    }

    DESKTOP_BINARIES: Dict[str, List[str]] = {
        "chrome": ["google-chrome", "google-chrome-stable", "chromium", "open -a 'Google Chrome'"],
        "firefox": ["firefox", "open -a Firefox"],
        "spotify": ["spotify", "open -a Spotify"],
        "terminal": ["x-terminal-emulator", "gnome-terminal", "alacritty", "konsole", "open -a Terminal"]
    }

    def __init__(self, db_path: Optional[Path] = None):
        self.env = self._interrogate_environment()
        self.screen_width = self.env.screen_width
        self.screen_height = self.env.screen_height
        self.layout_cache = AppLayoutCache(db_path=db_path)

    # ----------------------------------------------------------------------
    # 1. Environment & Live Permission Interrogation
    # ----------------------------------------------------------------------
    def _interrogate_environment(self) -> DeviceEnvironment:
        is_android = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ
        os_sys = platform.system().lower()

        if is_android:
            os_family = "android"
            display_server = "android_surface"
        elif "darwin" in os_sys:
            os_family = "darwin"
            display_server = "cocoa"
        elif "win" in os_sys:
            os_family = "windows"
            display_server = "win32"
        elif "linux" in os_sys:
            os_family = "linux"
            display_server = "wayland" if "WAYLAND_DISPLAY" in os.environ else ("x11" if "DISPLAY" in os.environ else "headless")
        else:
            os_family = "unknown"
            display_server = "headless"

        has_root = False
        has_rish = False
        has_adb = False
        has_termux_api = False
        input_driver = "simulated"
        perm_note = "Touch simulation mode"

        if is_android:
            has_termux_api = bool(shutil.which("termux-open-url"))

            # 1. Probe Root (su)
            if shutil.which("su"):
                try:
                    res = subprocess.run(["su", "-c", "id"], capture_output=True, timeout=1)
                    has_root = res.returncode == 0 and b"uid=0" in res.stdout
                except Exception:
                    has_root = False

            # 2. Probe Shizuku / Rish
            if not has_root and shutil.which("rish"):
                try:
                    res = subprocess.run(["rish", "-c", "id"], capture_output=True, timeout=1)
                    has_rish = res.returncode == 0
                except Exception:
                    has_rish = False

            # 3. Probe Local ADB connection
            if not has_root and not has_rish and shutil.which("adb"):
                try:
                    res = subprocess.run(["adb", "get-state"], capture_output=True, text=True, timeout=1)
                    if "device" in res.stdout:
                        has_adb = True
                except Exception:
                    has_adb = False

            # 4. Select and Test Working Android Input Driver
            if has_root:
                input_driver = "su_input"
                perm_note = "Elevated Root touch injection active"
            elif has_rish:
                input_driver = "rish_input"
                perm_note = "Elevated Shizuku/Rish touch injection active"
            elif has_adb:
                input_driver = "adb_input"
                perm_note = "Local ADB wireless touch injection active"
            else:
                # Test if raw input command has INJECT_EVENTS permission
                if shutil.which("input"):
                    try:
                        test_cmd = subprocess.run(["input", "keyevent", "0"], capture_output=True, timeout=1)
                        if test_cmd.returncode == 0:
                            input_driver = "termux_input"
                            perm_note = "Standard shell input active"
                        else:
                            input_driver = "simulated"
                            perm_note = "Android INJECT_EVENTS restricted (Pair via 'adb' or Shizuku for physical touches)"
                    except Exception:
                        input_driver = "simulated"
                        perm_note = "Restricted Android userland. Simulated coordinates active."

        elif os_family == "linux":
            if display_server == "x11" and shutil.which("xdotool"):
                input_driver = "xdotool"
                perm_note = "X11 xdotool active"
            elif display_server == "wayland" and shutil.which("ydotool"):
                input_driver = "ydotool"
                perm_note = "Wayland ydotool active"

        elif os_family == "darwin" and shutil.which("osascript"):
            input_driver = "osascript"
            perm_note = "macOS AppleScript automation active"

        w, h = self._probe_display_resolution(is_android, display_server)

        return DeviceEnvironment(
            os_family=os_family,
            is_android=is_android,
            has_root=has_root,
            has_rish=has_rish,
            has_adb=has_adb,
            has_termux_api=has_termux_api,
            display_server=display_server,
            input_driver=input_driver,
            screen_width=w,
            screen_height=h,
            permission_note=perm_note
        )

    def _probe_display_resolution(self, is_android: bool, display_server: str) -> Tuple[int, int]:
        if is_android:
            try:
                res = subprocess.run(["wm", "size"], capture_output=True, text=True, timeout=2)
                if "Physical size:" in res.stdout:
                    parts = res.stdout.split("Physical size:")[1].strip().split("x")
                    return int(parts[0]), int(parts[1])
            except Exception:
                pass
            return 1080, 2400

        if display_server == "x11" and shutil.which("xrandr"):
            try:
                res = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=2)
                for line in res.stdout.splitlines():
                    if " connected" in line and "+" in line:
                        geom = line.split()[2].split("+")[0].split("x")
                        return int(geom[0]), int(geom[1])
            except Exception:
                pass

        return 1920, 1080

    # ----------------------------------------------------------------------
    # 2. Universal Execution Dispatcher
    # ----------------------------------------------------------------------
    def _execute_shell(self, cmd_args: List[str]) -> Tuple[bool, str]:
        if self.env.input_driver == "su_input":
            cmd = ["su", "-c", " ".join(cmd_args)]
        elif self.env.input_driver == "rish_input":
            cmd = ["rish", "-c", " ".join(cmd_args)]
        elif self.env.input_driver == "adb_input":
            cmd = ["adb", "shell"] + cmd_args
        else:
            cmd = cmd_args

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            return res.returncode == 0, res.stdout.strip() or res.stderr.strip()
        except Exception as e:
            return False, str(e)

    # ----------------------------------------------------------------------
    # 3. Application Launching & Task Switching
    # ----------------------------------------------------------------------
    def open_app(self, app_name: str) -> Tuple[bool, str]:
        name_clean = app_name.lower().strip()

        if self.env.is_android:
            pkg = self.ANDROID_PACKAGES.get(name_clean, name_clean)

            # Activity Manager Intent launch
            ok, out = self._execute_shell(["am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", pkg])
            if ok:
                return True, f"Launched Android package: {pkg}"

            # Fallback to Termux-Open-URL
            if self.env.has_termux_api:
                ok_url, _ = self._execute_shell(["termux-open-url", f"https://{name_clean}.com"])
                if ok_url:
                    return True, f"Opened web intent for: {name_clean}"

            return False, f"Could not launch Android app: {pkg}"

        if self.env.os_family == "darwin":
            try:
                subprocess.Popen(["open", "-a", app_name])
                return True, f"Launched macOS Application: {app_name}"
            except Exception:
                return False, f"macOS launch failed for: {app_name}"

        if self.env.os_family == "linux":
            bin_candidates = self.DESKTOP_BINARIES.get(name_clean, [name_clean])
            for binary in bin_candidates:
                bin_name = binary.split()[0]
                if shutil.which(bin_name):
                    subprocess.Popen(binary, shell=True)
                    return True, f"Launched Linux application: {bin_name}"

        return False, f"Launcher not found for: {app_name}"

    # ----------------------------------------------------------------------
    # 4. Touch, Mouse & Gestures (Hardware or Clean Simulation)
    # ----------------------------------------------------------------------
    def tap(self, x: int, y: int) -> bool:
        x_clamped = max(0, min(self.screen_width, x))
        y_clamped = max(0, min(self.screen_height, y))

        if self.env.input_driver in ("su_input", "rish_input", "adb_input", "termux_input"):
            ok, _ = self._execute_shell(["input", "tap", str(x_clamped), str(y_clamped)])
            return ok

        if self.env.input_driver == "xdotool":
            ok, _ = self._execute_shell(["xdotool", "mousemove", str(x_clamped), str(y_clamped), "click", "1"])
            return ok

        # Simulation mode: returns True and logs the resolved coordinates
        return True

    def scroll(self, direction: str = "down", intensity: float = 0.5) -> bool:
        cx = self.screen_width // 2
        cy = self.screen_height // 2
        distance = int((self.screen_height * 0.4) * max(0.1, min(1.0, intensity)))

        if self.env.input_driver in ("su_input", "rish_input", "adb_input", "termux_input"):
            if direction == "down":
                x1, y1 = cx, cy + (distance // 2)
                x2, y2 = cx, cy - (distance // 2)
            elif direction == "up":
                x1, y1 = cx, cy - (distance // 2)
                x2, y2 = cx, cy + (distance // 2)
            elif direction == "right":
                x1, y1 = cx + 200, cy
                x2, y2 = cx - 200, cy
            else:
                x1, y1 = cx - 200, cy
                x2, y2 = cx + 200, cy

            ok, _ = self._execute_shell(["input", "swipe", str(x1), str(y1), str(x2), str(y2), "280"])
            return ok

        if self.env.input_driver == "xdotool":
            btn = "5" if direction == "down" else "4"
            ok, _ = self._execute_shell(["xdotool", "click", "--repeat", "3", btn])
            return ok

        return True

    def click_element(self, app_alias_or_pkg: str, element_key: str) -> Tuple[bool, str]:
        pkg = self.ANDROID_PACKAGES.get(app_alias_or_pkg.lower(), app_alias_or_pkg)

        coords = self.layout_cache.get_coordinates(pkg, element_key, self.screen_width, self.screen_height)
        if coords:
            x, y = coords
            self.tap(x, y)
            mode = "Physical Tap" if self.env.input_driver != "simulated" else "Simulated Tap"
            return True, f"[{mode}] Tapped '{element_key}' at ({x}, {y})"

        return False, f"Element '{element_key}' could not be resolved."

    def type_text(self, text: str) -> bool:
        if self.env.input_driver in ("su_input", "rish_input", "adb_input", "termux_input"):
            sanitized = text.replace(" ", "%s").replace("'", "\\'")
            ok, _ = self._execute_shell(["input", "text", sanitized])
            return ok

        return True

    def press_key(self, key_name: str) -> bool:
        key_upper = key_name.upper()

        if self.env.input_driver in ("su_input", "rish_input", "adb_input", "termux_input"):
            android_keycodes = {
                "HOME": "3", "BACK": "4", "ENTER": "66",
                "APP_SWITCH": "187", "VOLUME_UP": "24", "VOLUME_DOWN": "25"
            }
            code = android_keycodes.get(key_upper)
            if code:
                ok, _ = self._execute_shell(["input", "keyevent", code])
                return ok

        return True
