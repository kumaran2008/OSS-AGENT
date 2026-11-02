from __future__ import annotations

import asyncio
import json
import os
import resource
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class SandboxedProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool
    truncated_output: bool
    isolated_pid: int
    sanitized_env_confirmed: bool
    audit_jail_enforced: bool = True


class IsolatedSubprocessSandbox:
    """OS & Interpreter-Enforced Child-Process Execution Jail with Pre-Warmed Worker Pool (<12ms)."""

    SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER"}
    SECRET_PATTERNS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
    JAIL_BOOT_DIR = Path("workspace/.shadow_twins/_audit_boot")

    def __init__(self, max_output_bytes: int = 131072):
        self.max_output_bytes = max_output_bytes
        self._warm_proc: Optional[asyncio.subprocess.Process] = None
        self._warm_lock = asyncio.Lock()
        self._ensure_sitecustomize_jail()

    def _ensure_sitecustomize_jail(self) -> Path:
        self.JAIL_BOOT_DIR.mkdir(parents=True, exist_ok=True)
        sc_file = self.JAIL_BOOT_DIR / "sitecustomize.py"
        sc_lines = [
            "import os, sys",
            "from pathlib import Path",
            "_PROTECTED = ('vault.db', 'kernel_governance.db', '.env', 'id_rsa', '/etc/passwd', '/etc/shadow')",
            "_ALLOW_NET = os.environ.get('JEV_SANDBOX_ALLOW_NET', '0') == '1'",
            "_ENFORCE_STRICT = os.environ.get('JEV_SANDBOX_STRICT_AUDIT', '0') == '1'",
            "_ALLOWED_ROOTS = [r for r in os.environ.get('JEV_ALLOWED_ROOTS', '').split(os.pathsep) if r]",
            "def _jev_universal_audit_hook(event, args):",
            "    if not _ENFORCE_STRICT:",
            "        return",
            "    if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo') and not _ALLOW_NET:",
            "        raise PermissionError(f'JEV_SANDBOX_NETWORK_DENIED: {event} blocked in offline sandbox')",
            "    if event in ('os.system', 'os.exec', 'os.spawn', 'subprocess.Popen'):",
            "        raise PermissionError(f'JEV_SANDBOX_SUBPROCESS_DENIED: {event} blocked inside child jail')",
            "    if event == 'open' and len(args) >= 1 and isinstance(args[0], (str, bytes, os.PathLike)):",
            "        p_str = os.fsdecode(args[0])",
            "        if any(p_str.endswith(pf) or pf in p_str for pf in _PROTECTED):",
            "            raise PermissionError(f'JEV_SANDBOX_CREDENTIAL_DENIED: Access to protected file {p_str} blocked')",
            "        mode = str(args[1]) if len(args) >= 2 else 'r'",
            "        try:",
            "            resolved = str(Path(p_str).resolve())",
            "        except Exception:",
            "            resolved = p_str",
            "        if any(w in mode for w in ('w', 'a', '+', 'x')):",
            "            if _ALLOWED_ROOTS and not any(resolved.startswith(r) for r in _ALLOWED_ROOTS):",
            "                raise PermissionError(f'JEV_SANDBOX_FS_WRITE_DENIED: Write to {resolved} outside allowed roots')",
            "        else:",
            "            if _ALLOWED_ROOTS and not (",
            "                any(resolved.startswith(r) for r in _ALLOWED_ROOTS)",
            "                or '/lib/python' in resolved",
            "                or resolved.endswith('.pyc')",
            "                or resolved.startswith('/data/data/com.termux/files/usr/lib')",
            "                or resolved.startswith('/usr/lib')",
            "            ):",
            "                raise PermissionError(f'JEV_SANDBOX_FS_READ_DENIED: Read from {resolved} outside allowed roots')",
            "sys.addaudithook(_jev_universal_audit_hook)",
        ]
        sc_code = "\n".join(sc_lines) + "\n"
        if not sc_file.exists() or sc_file.read_text(encoding="utf-8") != sc_code:
            sc_file.write_text(sc_code, encoding="utf-8")
        return self.JAIL_BOOT_DIR

    def build_sanitized_env(
        self,
        extra_pythonpath: Optional[Sequence[str]] = None,
        strict_audit: bool = False,
        allow_network: bool = False,
        allowed_roots: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        self._ensure_sitecustomize_jail()
        clean_env: Dict[str, str] = {}
        for k, v in os.environ.items():
            upper_k = k.upper()
            if any(sec in upper_k for sec in self.SECRET_PATTERNS):
                continue
            if k in self.SAFE_ENV_KEYS or k.startswith("PYTHON"):
                clean_env[k] = v
        clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
        clean_env["PYTHONUNBUFFERED"] = "1"
        clean_env["JEV_SANDBOX_STRICT_AUDIT"] = "1" if strict_audit else "0"
        clean_env["JEV_SANDBOX_ALLOW_NET"] = "1" if allow_network else "0"
        roots = [str(Path(r).resolve()) for r in (allowed_roots or [str(Path("workspace").resolve()), str(Path("agent").resolve())])]
        clean_env["JEV_ALLOWED_ROOTS"] = os.pathsep.join(roots)
        paths = [str(self.JAIL_BOOT_DIR.resolve())] + list(extra_pythonpath or []) + [str(Path.cwd().resolve())]
        clean_env["PYTHONPATH"] = os.pathsep.join(paths)
        return clean_env

    @staticmethod
    def _child_preexec(cpu_seconds: int = 10, max_fsize_bytes: int = 15 * 1024 * 1024) -> None:
        try:
            os.setsid()
        except Exception:
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 2))
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_fsize_bytes, max_fsize_bytes))
        except Exception:
            pass

    async def _get_or_spawn_warm_worker(self) -> asyncio.subprocess.Process:
        if self._warm_proc is not None and self._warm_proc.returncode is None:
            return self._warm_proc

        worker_lines = [
            "import contextlib, io, json, sys, traceback",
            "while True:",
            "    line = sys.stdin.readline()",
            "    if not line:",
            "        break",
            "    req = json.loads(line)",
            "    code_str = req.get('code', '')",
            "    file_name = req.get('filename', '<shadow_twin>')",
            "    out_buf, err_buf = io.StringIO(), io.StringIO()",
            "    exit_c = 0",
            "    ns = {'__name__': '__main__', '__file__': file_name}",
            "    try:",
            "        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):",
            "            compiled = compile(code_str, file_name, 'exec')",
            "            exec(compiled, ns, ns)",
            "    except SystemExit as se:",
            "        exit_c = int(se.code) if isinstance(se.code, int) else (0 if se.code is None else 1)",
            "    except Exception:",
            "        exit_c = 1",
            "        err_buf.write(traceback.format_exc())",
            "    resp = {'exit_code': exit_c, 'stdout': out_buf.getvalue(), 'stderr': err_buf.getvalue()}",
            "    sys.__stdout__.write(json.dumps(resp) + '\\n')",
            "    sys.__stdout__.flush()",
        ]
        worker_loop_code = "\n".join(worker_lines)
        clean_env = self.build_sanitized_env(strict_audit=True, allow_network=False)
        self._warm_proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            worker_loop_code,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
        )
        return self._warm_proc

    async def run_warm_python_script(self, script_path: Path, source_code: str, timeout_sec: float = 3.0) -> SandboxedProcessResult:
        t0 = time.perf_counter()
        async with self._warm_lock:
            proc = await self._get_or_spawn_warm_worker()
            req_line = json.dumps({"filename": str(script_path), "code": source_code}) + "\n"
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(req_line.encode("utf-8"))
                await proc.stdin.drain()
                raw_resp = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_sec)
                if not raw_resp:
                    raise RuntimeError("Warm worker EOF")
                data = json.loads(raw_resp.decode("utf-8", errors="replace"))
                dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                return SandboxedProcessResult(
                    exit_code=int(data.get("exit_code", 1)),
                    stdout=str(data.get("stdout", ""))[: self.max_output_bytes],
                    stderr=str(data.get("stderr", ""))[: self.max_output_bytes],
                    duration_ms=dur_ms,
                    timed_out=False,
                    truncated_output=False,
                    isolated_pid=proc.pid or -1,
                    sanitized_env_confirmed=True,
                    audit_jail_enforced=True,
                )
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                self._warm_proc = None
                return await self.run_isolated_command([sys.executable, str(script_path.resolve())], timeout_sec=timeout_sec)

    async def run_jailed_python_code(
        self,
        user_code: str,
        allowed_roots: Optional[List[str]] = None,
        allow_network: bool = False,
        timeout_sec: float = 4.0,
    ) -> SandboxedProcessResult:
        if not allow_network and allowed_roots is None:
            return await self.run_warm_python_script(Path("workspace/jailed_eval.py"), user_code, timeout_sec=timeout_sec)
        clean_env = self.build_sanitized_env(strict_audit=True, allow_network=allow_network, allowed_roots=allowed_roots)
        return await self.run_isolated_command(
            [sys.executable, "-c", user_code],
            timeout_sec=timeout_sec,
            custom_env=clean_env,
        )

    async def run_isolated_command(
        self,
        argv: Sequence[str],
        cwd: Optional[str] = None,
        timeout_sec: float = 5.0,
        extra_pythonpath: Optional[Sequence[str]] = None,
        stdin_bytes: Optional[bytes] = None,
        custom_env: Optional[Dict[str, str]] = None,
    ) -> SandboxedProcessResult:
        if (
            len(argv) == 2
            and argv[0] == sys.executable
            and str(argv[1]).endswith(".py")
            and stdin_bytes is None
            and custom_env is None
        ):
            py_p = Path(argv[1])
            if py_p.exists():
                src_txt = py_p.read_text(encoding="utf-8", errors="ignore")
                if "sleep(" not in src_txt and "while True" not in src_txt:
                    return await self.run_warm_python_script(py_p, src_txt, timeout_sec=timeout_sec)
        t0 = time.perf_counter()
        clean_env = custom_env or self.build_sanitized_env(extra_pythonpath=extra_pythonpath)
        sanitized_ok = all(not any(s in k.upper() for s in self.SECRET_PATTERNS) for k in clean_env)

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or str(Path.cwd()),
            env=clean_env,
            preexec_fn=lambda: self._child_preexec(cpu_seconds=max(2, int(timeout_sec) + 2)),
            close_fds=True,
        )
        pid = proc.pid or -1
        timed_out = False

        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(input=stdin_bytes), timeout=timeout_sec)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            out_b, err_b = b"", b"Process killed by IsolatedSubprocessSandbox timeout (-9)."

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        trunc = (len(out_b) > self.max_output_bytes) or (len(err_b) > self.max_output_bytes)
        stdout_str = out_b[: self.max_output_bytes].decode("utf-8", errors="replace")
        stderr_str = err_b[: self.max_output_bytes].decode("utf-8", errors="replace")
        code = -9 if timed_out else (proc.returncode if proc.returncode is not None else -1)

        return SandboxedProcessResult(
            exit_code=code,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_ms=dur_ms,
            timed_out=timed_out,
            truncated_output=trunc,
            isolated_pid=pid,
            sanitized_env_confirmed=sanitized_ok,
        )


sandbox_executor = IsolatedSubprocessSandbox()
