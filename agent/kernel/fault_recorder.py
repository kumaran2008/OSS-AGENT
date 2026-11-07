from __future__ import annotations

import functools
import hashlib
import inspect
import json
import linecache
import platform
import re
import sqlite3
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class FaultRecord:
    fault_id: str
    dedup_hash: str
    subsystem: str
    exception_type: str
    error_message: str
    file_path: str
    function_name: str
    line_number: int
    exact_code_block: str
    local_variables: Dict[str, str]
    traceback_text: str
    occurrence_count: int = 1
    first_seen_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    resolution_status: str = "OPEN"


class DiagnosticFaultRecorder:
    """Single-file fault ledger writing to workspace/diagnostic_fault_ledger.json."""

    JSON_LEDGER_PATH = Path("workspace/diagnostic_fault_ledger.json")
    MD_REPORT_PATH = Path("workspace/DIAGNOSTIC_FAULTS.md")
    DB_PATH = Path("workspace/kernel_governance.db")

    SECRET_RE = re.compile(
        r"(?:key|token|secret|password|auth|sk-[a-zA-Z0-9_\-]{10,})",
        re.IGNORECASE,
    )

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self._lock = threading.RLock()
        self.JSON_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, FaultRecord] = {}
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kernel_fault_ledger ("
                "dedup_hash TEXT PRIMARY KEY, fault_id TEXT, subsystem TEXT, "
                "exception_type TEXT, error_message TEXT, file_path TEXT, "
                "function_name TEXT, line_number INTEGER, exact_code_block TEXT, "
                "local_variables_json TEXT, traceback_text TEXT, "
                "occurrence_count INTEGER, first_seen_at REAL, "
                "last_seen_at REAL, resolution_status TEXT)"
            )
            conn.commit()

    @classmethod
    def _scrub(cls, k: str, v: Any) -> str:
        if cls.SECRET_RE.search(k):
            return "[REDACTED]"
        try:
            txt = repr(v)
        except Exception:
            txt = "<unreprable>"
        if cls.SECRET_RE.search(txt):
            return "[REDACTED]"
        return txt[:180]

    def _code_window(self, filepath: str, lineno: int, radius: int = 6) -> str:
        linecache.checkcache(filepath)
        out: List[str] = []
        for idx in range(max(1, lineno - radius), lineno + radius + 1):
            line = linecache.getline(filepath, idx)
            if not line and idx > lineno:
                break
            mark = ">>> " if idx == lineno else "    "
            out.append(f"{mark}{idx:4d} | {line.rstrip()}")
        return "\n".join(out) if out else f"{filepath}:{lineno}"

    def record_exception(
        self,
        exc: BaseException,
        subsystem: str = "oryn",
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> FaultRecord:
        with self._lock:
            tb = exc.__traceback__
            frame = None
            lineno = 0
            curr = tb
            while curr is not None:
                f_name = curr.tb_frame.f_code.co_filename
                if "site-packages" not in f_name:
                    frame = curr.tb_frame
                    lineno = curr.tb_lineno
                curr = curr.tb_next

            if frame is not None:
                f_path = frame.f_code.co_filename
                fn_name = frame.f_code.co_name
                code_blk = self._code_window(f_path, lineno)
                l_vars = {
                    str(k): self._scrub(str(k), v)
                    for k, v in list(frame.f_locals.items())[:15]
                    if not str(k).startswith("__")
                }
            else:
                f_path, fn_name, code_blk, l_vars = "<unknown>", "<module>", "", {}

            if extra_context:
                for k, v in extra_context.items():
                    l_vars[f"ctx.{k}"] = self._scrub(str(k), v)

            exc_name = type(exc).__name__
            msg = str(exc).strip() or repr(exc)
            tb_str = "".join(traceback.format_exception(type(exc), exc, tb))
            sig = f"{subsystem}|{f_path}|{fn_name}|{lineno}|{exc_name}"
            d_hash = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]
            now = time.time()

            if d_hash in self._records:
                rec = self._records[d_hash]
                rec.occurrence_count += 1
                rec.last_seen_at = now
            else:
                rec = FaultRecord(
                    fault_id=f"flt_{int(now * 1000)}_{d_hash[:6]}",
                    dedup_hash=d_hash,
                    subsystem=subsystem,
                    exception_type=exc_name,
                    error_message=msg,
                    file_path=f_path,
                    function_name=fn_name,
                    line_number=lineno,
                    exact_code_block=code_blk,
                    local_variables=l_vars,
                    traceback_text=tb_str,
                )
                self._records[d_hash] = rec

            self._save(rec)
            return rec

    def record_custom_fault(
        self,
        subsystem: str,
        file_path: str,
        line_number: int,
        function_name: str,
        error_type: str,
        error_message: str,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> FaultRecord:
        err = RuntimeError(f"{error_type}: {error_message}")
        return self.record_exception(
            err,
            subsystem=subsystem,
            extra_context={"file": file_path, "line": line_number, **(extra_context or {})},
        )

    def _save(self, rec: FaultRecord) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kernel_fault_ledger VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.dedup_hash,
                    rec.fault_id,
                    rec.subsystem,
                    rec.exception_type,
                    rec.error_message,
                    rec.file_path,
                    rec.function_name,
                    rec.line_number,
                    rec.exact_code_block,
                    json.dumps(rec.local_variables),
                    rec.traceback_text,
                    rec.occurrence_count,
                    rec.first_seen_at,
                    rec.last_seen_at,
                    rec.resolution_status,
                ),
            )
            conn.commit()

        data = {
            "updated_at": time.time(),
            "platform": platform.platform(),
            "faults": [asdict(r) for r in self._records.values()],
        }
        self.JSON_LEDGER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

        lines = ["# ORYN DIAGNOSTIC FAULT LEDGER", ""]
        for r in self._records.values():
            lines.append(f"## [{r.resolution_status}] {r.fault_id} - {r.exception_type}")
            lines.append(f"- File: `{r.file_path}` ({r.function_name}:{r.line_number})")
            lines.append(f"- Error: `{r.error_message}`")
            lines.append("```python")
            lines.append(r.exact_code_block)
            lines.append("```")
            lines.append("")
        self.MD_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    def guard(self, subsystem: str = "oryn") -> Callable[[F], F]:
        def decorator(func: F) -> F:
            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def aw(*args: Any, **kwargs: Any) -> Any:
                    try:
                        return await func(*args, **kwargs)
                    except BaseException as e:
                        self.record_exception(e, subsystem=subsystem)
                        raise
                return aw  # type: ignore[return-value]

            @functools.wraps(func)
            def sw(*args: Any, **kwargs: Any) -> Any:
                try:
                    return func(*args, **kwargs)
                except BaseException as e:
                    self.record_exception(e, subsystem=subsystem)
                    raise
            return sw  # type: ignore[return-value]
        return decorator

    def install_global_hooks(self) -> None:
        pass


fault_recorder = DiagnosticFaultRecorder()
