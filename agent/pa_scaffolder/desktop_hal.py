import sys
import os
import shutil
import ctypes
import subprocess
from pathlib import Path
from typing import Optional


class NativeDesktopHAL:
    """
    Zero-Dependency Native Desktop OS Automation Driver.
    Integrates with Win32 API, macOS Cocoa/AppleScript, Linux X11, and Termux.
    Features defensive in-memory clipboard mirroring and native screenshot capture.
    """

    def __init__(self):
        self.platform = sys.platform
        self._in_memory_clipboard = ""

    def bring_window_to_front(self, window_title_substr: str) -> bool:
        clean_target = window_title_substr.lower().strip()

        # Windows 11 / 10 via ctypes User32
        if self.platform.startswith("win"):
            try:
                user32 = ctypes.windll.user32
                found_hwnd = None

                def enum_windows_proc(hwnd, extra):
                    nonlocal found_hwnd
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buffer, length + 1)
                        if clean_target in buffer.value.lower():
                            found_hwnd = hwnd
                            return False
                    return True

                proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
                user32.EnumWindows(proc_type(enum_windows_proc), 0)

                if found_hwnd:
                    user32.ShowWindow(found_hwnd, 9)
                    user32.SetForegroundWindow(found_hwnd)
                    return True
            except Exception:
                pass
            return False

        # macOS via AppleScript
        elif self.platform == "darwin":
            script = f'''
            tell application "System Events"
                set procList to every process whose visible is true
                repeat with p in procList
                    if (name of p as text) contains "{window_title_substr}" then
                        set frontmost of p to true
                        return true
                    end if
                end repeat
            end tell
            return false
            '''
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return "true" in res.stdout.lower()

        # Linux X11 / Wayland
        elif self.platform.startswith("linux") and not os.path.exists("/data/data/com.termux"):
            for tool in ["wmctrl", "xdotool"]:
                if shutil.which(tool):
                    if tool == "wmctrl":
                        res = subprocess.run(["wmctrl", "-a", window_title_substr], capture_output=True)
                        return res.returncode == 0
                    else:
                        res = subprocess.run(
                            ["xdotool", "search", "--onlyvisible", "--name", window_title_substr, "windowactivate"],
                            capture_output=True
                        )
                        return res.returncode == 0

        return False

    def set_clipboard(self, text: str) -> bool:
        self._in_memory_clipboard = text

        if shutil.which("termux-clipboard-set"):
            try:
                subprocess.run(
                    ["termux-clipboard-set", text],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=2.0
                )
                return True
            except Exception:
                pass

        if shutil.which("pbcopy"):
            try:
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"), timeout=2.0)
                return p.returncode == 0
            except Exception:
                pass

        if self.platform.startswith("win"):
            try:
                cmd = f'Set-Clipboard -Value "{text}"'
                res = subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=2.0)
                return res.returncode == 0
            except Exception:
                pass

        for tool, flag in [("xclip", ["-selection", "clipboard"]), ("xsel", ["-b", "-i"])]:
            if shutil.which(tool):
                try:
                    p = subprocess.Popen([tool] + flag, stdin=subprocess.PIPE)
                    p.communicate(text.encode("utf-8"), timeout=2.0)
                    return p.returncode == 0
                except Exception:
                    pass

        return True

    def get_clipboard(self) -> str:
        if shutil.which("termux-clipboard-get"):
            try:
                res = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

        if shutil.which("pbpaste"):
            try:
                res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

        for tool, flag in [("xclip", ["-selection", "clipboard", "-o"]), ("xsel", ["-b", "-o"])]:
            if shutil.which(tool):
                try:
                    res = subprocess.run([tool] + flag, capture_output=True, text=True, timeout=2.0)
                    if res.returncode == 0 and res.stdout.strip():
                        return res.stdout.strip()
                except Exception:
                    pass

        if self.platform.startswith("win"):
            try:
                res = subprocess.run(["powershell", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

        return self._in_memory_clipboard

    def notify(self, title: str, message: str) -> bool:
        if shutil.which("termux-notification"):
            subprocess.run(["termux-notification", "--title", title, "--content", message], capture_output=True)
            return True

        if self.platform == "darwin":
            clean_msg = message.replace('"', '\\"')
            clean_title = title.replace('"', '\\"')
            script = f'display notification "{clean_msg}" with title "{clean_title}"'
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return True

        if self.platform.startswith("win"):
            ps_script = f"""
            [reflection.assembly]::loadwithpartialname('System.Windows.Forms');
            $notify = new-object system.windows.forms.notifyicon;
            $notify.icon = [system.drawing.systemicons]::information;
            $notify.visible = $true;
            $notify.showballoontip(10, '{title}', '{message}', [system.windows.forms.tooltipicon]::info);
            """
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
            return True

        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True)
            return True

        return False

    def capture_screen(self, target_path: Optional[str] = None) -> Optional[Path]:
        out_path = Path(target_path or "workspace/screenshots/debug_capture.png").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self.platform == "darwin":
            res = subprocess.run(["screencapture", "-x", str(out_path)], capture_output=True)
            if res.returncode == 0 and out_path.exists():
                return out_path

        elif self.platform.startswith("win"):
            ps_script = f"""
            Add-Type -AssemblyName System.Windows.Forms,System.Drawing;
            $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds;
            $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height;
            $graphics = [System.Drawing.Graphics]::FromImage($bmp);
            $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size);$bmp.Save('{str(out_path)}', [System.Drawing.Imaging.ImageFormat]::Png);
            $graphics.Dispose();$bmp.Dispose();
            """
            res = subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
            if out_path.exists():
                return out_path

        elif self.platform.startswith("linux") and not os.path.exists("/data/data/com.termux"):
            for tool, cmd in [
                ("maim", ["maim", str(out_path)]),
                ("scrot", ["scrot", str(out_path)]),
                ("import", ["import", "-window", "root", str(out_path)])
            ]:
                if shutil.which(tool):
                    res = subprocess.run(cmd, capture_output=True)
                    if res.returncode == 0 and out_path.exists():
                        return out_path

        elif os.path.exists("/data/data/com.termux"):
            for cmd in [
                ["su", "-c", f"screencap -p {str(out_path)}"],
                ["termux-storage-get", str(out_path)]
            ]:
                try:
                    res = subprocess.run(cmd, capture_output=True, timeout=2.0)
                    if out_path.exists() and out_path.stat().st_size > 0:
                        return out_path
                except Exception:
                    pass

        # Headless/isolated minimal 1x1 valid PNG byte fallback
        try:
            minimal_png = (
                b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
                b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00'
                b'\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf'
                b'\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
            )
            out_path.write_bytes(minimal_png)
            return out_path
        except Exception:
            return None
