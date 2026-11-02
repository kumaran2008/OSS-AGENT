import os
import sys
import time
import subprocess
from typing import Optional


class NativeCompanionWindow:
    """
    Spawns a native, borderless, transparent, always-on-top desktop
    window or mobile overlay hosting the 3D companion face.
    """
    def __init__(self, port: int = 14242, width: int = 240, height: int = 240):
        self.port = port
        self.url = f"http://127.0.0.1:{self.port}"
        self.width = width
        self.height = height
        self.is_termux = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ

    def launch(self, block: bool = False) -> bool:
        """
        Attempts to spawn the transparent desktop overlay.
        Falls back to platform-appropriate viewports gracefully.
        """
        # 1. Check for pywebview on GUI Desktop environments
        try:
            import webview
            print(f"[*] Spawning native transparent overlay ({self.width}x{self.height})...")
            window = webview.create_window(
                title="Personal Agent Companion",
                url=self.url,
                width=self.width,
                height=self.height,
                frameless=True,
                transparent=True,
                on_top=True,
                easy_drag=True
            )
            webview.start(debug=False)
            return True
        except ImportError:
            pass
        except Exception as e:
            print(f"[Notice] Native window system note: {e}")

        # 2. Android / Termux Viewport Launch
        if self.is_termux:
            print(f"[*] Termux environment detected. Launching UI overlay bridge...")
            try:
                subprocess.Popen(
                    ["termux-open-url", self.url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
            except Exception:
                pass

        # 3. Standard OS browser dispatch
        try:
            import webbrowser
            webbrowser.open(self.url)
            return True
        except Exception:
            return False
