import asyncio
import os
import sys
import pty
import time
import fcntl
import select
import signal
import subprocess
import re
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List


class TerminalOutputSanitizer:
    """Strips VT100 / ANSI escape sequences, spinners, and carriage returns."""
    ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    BACKSPACE_RE = re.compile(r'.\x08')

    @classmethod
    def clean(cls, raw_bytes: bytes) -> str:
        text = raw_bytes.decode("utf-8", errors="replace")
        # 1. Normalize PTY CRLF line endings to standard LF
        text = text.replace("\r\n", "\n")
        lines = []
        for line in text.split("\n"):
            line = line.rstrip("\r")
            if "\r" in line:
                # Handle intra-line carriage returns (e.g. progress bar overwrites)
                sub_lines = [s for s in line.split("\r") if s]
                lines.append(sub_lines[-1] if sub_lines else "")
            else:
                lines.append(line)

        cleaned = "\n".join(lines)
        cleaned = cls.ANSI_ESCAPE_RE.sub('', cleaned)
        while cls.BACKSPACE_RE.search(cleaned):
            cleaned = cls.BACKSPACE_RE.sub('', cleaned)
        return cleaned.strip()


class InteractiveSandboxSession:
    """
    SOTA Process-Group Isolated PTY Sandbox.
    - True POSIX openpty() with echo suppression.
    - Process group isolation (os.setsid & os.killpg) to eliminate orphaned child processes.
    - Non-blocking I/O with selective timeouts.
    - Background daemon lifecycle tracking.
    """

    def __init__(self, workspace_root: str = "workspace"):
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.is_posix = not sys.platform.startswith("win")
        self.background_daemons: Dict[str, subprocess.Popen] = {}

    async def execute_and_collect(self, command: str, timeout: float = 30.0) -> Tuple[int, str]:
        """Asynchronous wrapper around execute_command."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.execute_command, command, timeout)

    def execute_command(
        self,
        command: str,
        timeout_sec: float = 30.0,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Tuple[int, str]:
        """
        Executes a command inside an isolated process group PTY session.
        Guarantees that child processes are cleaned up on timeout or failure.
        """
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = "120"
        env["LINES"] = "40"
        if env_vars:
            env.update(env_vars)

        if not self.is_posix:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(self.workspace_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env
            )
            try:
                out, _ = proc.communicate(timeout=timeout_sec)
                return proc.returncode, TerminalOutputSanitizer.clean(out)
            except subprocess.TimeoutExpired:
                proc.kill()
                return -1, f"Command timed out after {timeout_sec}s"

        # POSIX PTY Execution
        master_fd, slave_fd = pty.openpty()

        try:
            import termios
            attr = termios.tcgetattr(slave_fd)
            attr[3] = attr[3] & ~termios.ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attr)
        except Exception:
            pass

        try:
            proc = subprocess.Popen(
                ["/bin/sh", "-c", command],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(self.workspace_root),
                env=env,
                preexec_fn=os.setsid,
                close_fds=True
            )
            os.close(slave_fd)

            fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            raw_output = bytearray()
            start_time = time.monotonic()

            while True:
                ret = proc.poll()
                rlist, _, _ = select.select([master_fd], [], [], 0.05)

                if master_fd in rlist:
                    try:
                        chunk = os.read(master_fd, 8192)
                        if chunk:
                            raw_output.extend(chunk)
                    except (BlockingIOError, OSError):
                        pass

                if ret is not None:
                    time.sleep(0.05)
                    while True:
                        try:
                            chunk = os.read(master_fd, 8192)
                            if not chunk:
                                break
                            raw_output.extend(chunk)
                        except (BlockingIOError, OSError):
                            break
                    break

                if (time.monotonic() - start_time) > timeout_sec:
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    return -1, f"Execution timed out after {timeout_sec}s. Terminated process group."

            os.close(master_fd)
            clean_output = TerminalOutputSanitizer.clean(raw_output)
            return proc.returncode, clean_output

        except Exception as e:
            try:
                os.close(master_fd)
            except Exception:
                pass
            return 1, f"PTY Execution Failure: {str(e)}"

    def start_daemon(self, name: str, command: str) -> Tuple[bool, str]:
        if name in self.background_daemons and self.background_daemons[name].poll() is None:
            return False, f"Daemon '{name}' is already running (PID: {self.background_daemons[name].pid})."

        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(self.workspace_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if self.is_posix else None
        )
        self.background_daemons[name] = proc
        return True, f"Daemon '{name}' started (PID: {proc.pid})."

    def stop_daemon(self, name: str) -> bool:
        proc = self.background_daemons.get(name)
        if not proc:
            return False

        try:
            if self.is_posix:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
            del self.background_daemons[name]
            return True
        except Exception:
            return False

    def close(self):
        for name in list(self.background_daemons.keys()):
            self.stop_daemon(name)
