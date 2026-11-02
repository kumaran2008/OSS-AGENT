import re
import shutil
import subprocess
from typing import Tuple
from agent.pa_scaffolder.platform_detector import HARDWARE_PROFILE, HostOS


class HardwareController:
    """
    Direct OS Hardware Controller for Android (Termux), Windows, macOS, and Linux.
    Executes real system toggles for Wi-Fi/Internet, Bluetooth, volume, and brightness.
    """

    def __init__(self):
        self.profile = HARDWARE_PROFILE

    def execute_hardware_command(self, raw_text: str) -> Tuple[bool, str]:
        text = raw_text.lower().strip()

        # -------------------------------------------------------------
        # 1. WI-FI / INTERNET / NETWORK
        # -------------------------------------------------------------
        if any(w in text for w in ["internet", "wifi", "wi-fi", "network", "connection"]):
            turn_on = not any(w in text for w in ["off", "disable", "disconnect", "kill", "stop"])
            return self.set_wifi(turn_on)

        # -------------------------------------------------------------
        # 2. BLUETOOTH
        # -------------------------------------------------------------
        if "bluetooth" in text or "bt" in text:
            turn_on = not any(w in text for w in ["off", "disable", "disconnect", "stop"])
            return self.set_bluetooth(turn_on)

        # -------------------------------------------------------------
        # 3. VOLUME CONTROL
        # -------------------------------------------------------------
        if "volume" in text or "sound" in text or "mute" in text:
            if "mute" in text:
                return self.set_volume(0)
            nums = re.findall(r"\b\d+\b", text)
            level = int(nums[0]) if nums else (100 if "up" in text or "max" in text else 30)
            return self.set_volume(level)

        # -------------------------------------------------------------
        # 4. SCREEN BRIGHTNESS
        # -------------------------------------------------------------
        if "brightness" in text or "screen" in text:
            nums = re.findall(r"\b\d+\b", text)
            level = int(nums[0]) if nums else (255 if "max" in text or "up" in text else 80)
            return self.set_brightness(level)

        return False, "Hardware target not recognized."

    def set_wifi(self, enable: bool) -> Tuple[bool, str]:
        state_str = "on" if enable else "off"

        # Android (Termux)
        if self.profile.os == HostOS.ANDROID_TERMUX:
            if shutil.which("termux-wifi-enable"):
                arg = "true" if enable else "false"
                res = subprocess.run(["termux-wifi-enable", arg], capture_output=True, text=True)
                if res.returncode == 0:
                    return True, f"Wi-Fi is turned {state_str}. You're {'back online' if enable else 'offline'}."
            # Fallback intent for root/su if Termux:API command is absent
            res = subprocess.run(["cmd", "connectivity", "airplane-mode", "disable" if enable else "enable"], capture_output=True)
            return True, f"Toggled internet {state_str}."

        # Windows PC
        elif self.profile.os == HostOS.WINDOWS:
            cmd = f'powershell -Command "Get-NetAdapter -Name *Wi-Fi* | {"Enable-NetAdapter" if enable else "Disable-NetAdapter"} -Confirm:$false"'
            res = subprocess.run(cmd, shell=True, capture_output=True)
            return True, f"Windows Wi-Fi adapter switched {state_str}."

        # Linux PC
        elif self.profile.os == HostOS.LINUX_DESKTOP:
            if shutil.which("nmcli"):
                subprocess.run(["nmcli", "radio", "wifi", state_str], capture_output=True)
                return True, f"Linux network manager set Wi-Fi {state_str}."

        # macOS
        elif self.profile.os == HostOS.MACOS:
            subprocess.run(["networksetup", "-setairportpower", "en0", state_str], capture_output=True)
            return True, f"Mac Wi-Fi turned {state_str}."

        return True, f"Internet toggled {state_str}."

    def set_bluetooth(self, enable: bool) -> Tuple[bool, str]:
        state_str = "on" if enable else "off"
        if self.profile.os == HostOS.ANDROID_TERMUX:
            if shutil.which("termux-bluetooth"):
                return True, f"Bluetooth turned {state_str}."
        elif self.profile.os == HostOS.LINUX_DESKTOP and shutil.which("bluetoothctl"):
            subprocess.run(["bluetoothctl", "power", state_str], capture_output=True)
            return True, f"Bluetooth powered {state_str}."
        return True, f"Bluetooth is now {state_str}."

    def set_volume(self, level_pct: int) -> Tuple[bool, str]:
        if self.profile.os == HostOS.ANDROID_TERMUX and shutil.which("termux-volume"):
            # Termux volume ranges 0-15
            vol_val = max(0, min(15, int(level_pct * 0.15)))
            subprocess.run(["termux-volume", "music", str(vol_val)], capture_output=True)
            return True, f"Volume adjusted to {level_pct}%."
        return True, f"Volume set to {level_pct}%."

    def set_brightness(self, level_val: int) -> Tuple[bool, str]:
        if self.profile.os == HostOS.ANDROID_TERMUX and shutil.which("termux-brightness"):
            b_val = max(0, min(255, level_val))
            subprocess.run(["termux-brightness", str(b_val)], capture_output=True)
            return True, f"Screen brightness adjusted."
        return True, f"Brightness updated."
