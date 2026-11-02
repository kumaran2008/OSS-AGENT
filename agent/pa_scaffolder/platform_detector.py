import os
import sys
import platform
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class HostOS(str, Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX_DESKTOP = "linux_desktop"
    ANDROID_TERMUX = "android_termux"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HardwareProfile:
    """
    Immutable In-Memory Hardware Snapshot.
    Initialized once at boot; referenced by all sub-agents with O(1) RAM speed.
    """
    os: HostOS
    machine: str
    python_version: str
    has_onnx: bool
    has_faster_whisper: bool
    has_sounddevice: bool
    has_termux_api: bool
    has_termux_tts: bool
    has_desktop_chrome: bool
    preferred_tts: str
    preferred_stt: str


class PlatformDetector:
    _cached_profile: Optional[HardwareProfile] = None

    @classmethod
    def get_profile(cls) -> HardwareProfile:
        """Returns the in-memory singleton. Probes hardware only on the first call."""
        if cls._cached_profile is not None:
            return cls._cached_profile

        # 1. Detect Operating System
        sys_name = platform.system().lower()
        if (
            "TERMUX_VERSION" in os.environ
            or "ANDROID_ROOT" in os.environ
            or os.path.exists("/data/data/com.termux")
        ):
            host_os = HostOS.ANDROID_TERMUX
        elif sys_name == "windows":
            host_os = HostOS.WINDOWS
        elif sys_name == "darwin":
            host_os = HostOS.MACOS
        elif sys_name == "linux":
            host_os = HostOS.LINUX_DESKTOP
        else:
            host_os = HostOS.UNKNOWN

        # 2. Probe Library Capabilities (Run once)
        has_onnx = False
        try:
            import onnxruntime
            has_onnx = True
        except Exception:
            pass

        has_faster_whisper = False
        try:
            import faster_whisper
            has_faster_whisper = True
        except Exception:
            pass

        has_sounddevice = False
        try:
            import sounddevice
            has_sounddevice = True
        except Exception:
            pass

        # 3. Probe External CLI & Binaries (Run once)
        has_termux_api = shutil.which("termux-speech-to-text") is not None
        has_termux_tts = shutil.which("termux-tts-speak") is not None

        chrome_candidates = [
            "chrome", "google-chrome", "msedge", "chromium",
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ]
        has_desktop_chrome = any(shutil.which(c) or os.path.exists(c) for c in chrome_candidates)

        # 4. Determine Optimal Strategy for Host Architecture
        if has_onnx and os.path.exists("workspace/models/kokoro/kokoro-v1.0.int8.onnx"):
            preferred_tts = "KOKORO_ONNX"
        else:
            preferred_tts = "EDGE_TTS" if host_os == HostOS.ANDROID_TERMUX else "OS_NATIVE"

        if has_faster_whisper and has_sounddevice:
            preferred_stt = "FASTER_WHISPER"
        elif has_termux_api:
            preferred_stt = "TERMUX_API"
        else:
            preferred_stt = "CLI_FALLBACK"

        cls._cached_profile = HardwareProfile(
            os=host_os,
            machine=platform.machine(),
            python_version=sys.version.split()[0],
            has_onnx=has_onnx,
            has_faster_whisper=has_faster_whisper,
            has_sounddevice=has_sounddevice,
            has_termux_api=has_termux_api,
            has_termux_tts=has_termux_tts,
            has_desktop_chrome=has_desktop_chrome,
            preferred_tts=preferred_tts,
            preferred_stt=preferred_stt
        )
        return cls._cached_profile


# Bootstrapped once on import, stored in RAM for zero-latency retrieval
HARDWARE_PROFILE: HardwareProfile = PlatformDetector.get_profile()
