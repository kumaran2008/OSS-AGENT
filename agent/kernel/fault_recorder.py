from __future__ import annotations
import sys
import traceback
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

class DiagnosticFaultRecorder:
    def __init__(self, db_path: str = "workspace/kernel_governance.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_json = Path("workspace/diagnostic_fault_ledger.json")
        self.ledger_md = Path("workspace/DIAGNOSTIC_FAULTS.md")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute('''
                CREATE TABLE IF NOT EXISTS kernel_fault_ledger (
                    fault_id TEXT PRIMARY KEY,
                    timestamp REAL,
                    exception_type TEXT,
                    message TEXT,
                    file_path TEXT,
                    line_no INTEGER,
                    function_name TEXT,
                    traceback_text TEXT
                )
            ''')

    def scrub_secrets(self, state_dict: Dict[str, Any]) -> Dict[str, Any]:
        scrubbed = {}
        sensitive_keys = {"api_key", "secret", "token", "password", "auth", "credential"}
        for k, v in state_dict.items():
            if any(s in k.lower() for s in sensitive_keys):
                scrubbed[k] = "[SECRET_SCRUBBED]"
            else:
                scrubbed[k] = str(v)[:200]
        return scrubbed

    def record_fault(self, exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        tb_list = traceback.extract_tb(exc_tb)
        last_frame = tb_list[-1] if tb_list else None
        file_path = last_frame.filename if last_frame else "unknown"
        line_no = last_frame.lineno if last_frame else 0
        func_name = last_frame.name if last_frame else "unknown"
        exc_name = getattr(exc_type, "__name__", "Exception")
        msg = str(exc_value)
        fault_id = f"fault_{int(time.time() * 1000)}"

        # Capture surrounding source code if available
        surrounding_code = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                start = max(0, line_no - 8)
                end = min(len(lines), line_no + 7)
                for idx in range(start, end):
                    surrounding_code.append(f"{idx+1}: {lines[idx]}")
        except Exception:
            surrounding_code = ["Source code unavailable."]

        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        
        # Persist to SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO kernel_fault_ledger
                (fault_id, timestamp, exception_type, message, file_path, line_no, function_name, traceback_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (fault_id, time.time(), exc_name, msg, file_path, line_no, func_name, tb_text))

        # Append to DIAGNOSTIC_FAULTS.md
        md_entry = f"## Fault {fault_id}\n- **Time**: {time.ctime()}
- **Exception**: {exc_name}: {msg}\n- **Location**: `{file_path}:{line_no}` in `{func_name}`\n\n```python\n" + "".join(surrounding_code) + "\n```\n\n"
        with open(self.ledger_md, "a", encoding="utf-8") as f_md:
            f_md.write(md_entry)

    def install_global_hooks(self) -> None:
        def custom_excepthook(exc_type, exc_value, exc_tb):
            try:
                self.record_fault(exc_type, exc_value, exc_tb)
            except Exception as inner_err:
                print(f"FaultRecorder failed to log exception: {inner_err}", file=sys.stderr)
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        sys.excepthook = custom_excepthook
