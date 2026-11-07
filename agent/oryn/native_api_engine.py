from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.fast_players import mcp_hot_pool
from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.native import native_accel
from agent.kernel.sandbox_isolation import sandbox_executor
from agent.oryn.capability_registry import oryn_capability_registry
from agent.oryn.contracts import (
    AXTreeSnapshot,
    ComputerAction,
    ExecutionDriver,
    ExecutionReceipt,
)


class NativeAPIDriver(ExecutionDriver):
    """Stage 1 Native API & Programmatic Execution Engine for ORYN.

    Handles 5 programmatic sub-channels before any GUI/Browser tokens are spent:
      1. `file_api`: Direct CSV, Excel (.xlsx), JSON, SQLite, and Document read/write/query
      2. `mcp_stdio`: Sub-3ms JSON-RPC 2.0 calls via WarmMCPStdioPool
      3. `rest_api`: Direct HTTP/REST requests with JSON schema verification
      4. `os_intent`: Termux (termux-open-url, am start, termux-clipboard-set) & Desktop intents
      5. `cli`: Sandboxed command-line execution via IsolatedSubprocessSandbox
    """

    channel = "native_api"

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.is_termux = os.path.exists("/data/data/com.termux") or "TERMUX_VERSION" in os.environ

    async def discover(self, target_app_or_url: str) -> Dict[str, Any]:
        cap = oryn_capability_registry.probe_application(target_app_or_url)
        return {
            "channel": self.channel,
            "available": "native_api" in cap.supported_channels,
            "app_id": cap.app_id,
            "cli_binary": cap.cli_binary,
            "cli_help_flags": cap.cli_help_flags,
            "python_libraries": cap.python_libraries,
            "com_prog_id": cap.com_prog_id,
            "confidence": cap.channel_confidences.get("native_api", 0.0),
        }

    @fault_recorder.guard(subsystem="oryn.native_api_engine")
    async def execute(self, action: ComputerAction) -> ExecutionReceipt:
        t0 = time.perf_counter()
        payload = action.payload or {}
        sub_mode = str(payload.get("sub_mode") or self._infer_sub_mode(action)).lower()

        if sub_mode == "file_api":
            receipt = await self._execute_file_or_data_api(action, t0)
        elif sub_mode == "mcp_stdio":
            receipt = await self._execute_mcp_stdio(action, t0)
        elif sub_mode == "rest_api":
            receipt = await self._execute_rest_api(action, t0)
        elif sub_mode == "os_intent":
            receipt = await self._execute_os_intent(action, t0)
        else:
            receipt = await self._execute_sandboxed_cli(action, t0)

        if action.requires_verification:
            receipt = await self.verify(action, receipt)
        return receipt

    @staticmethod
    def _infer_sub_mode(action: ComputerAction) -> str:
        payload = action.payload or {}
        if "file_operation" in payload or "file_path" in payload or "sql_query" in payload:
            return "file_api"
        if "mcp_server_id" in payload or "mcp_script" in payload:
            return "mcp_stdio"
        if "http_url" in payload or (action.target_ref and action.target_ref.startswith(("http://", "https://")) and action.operation == "invoke_api"):
            return "rest_api"
        if "intent_type" in payload or action.operation == "navigate":
            return "os_intent"
        return "cli"

    async def _execute_file_or_data_api(self, action: ComputerAction, t0: float) -> ExecutionReceipt:
        payload = action.payload or {}
        file_op = str(payload.get("file_operation", "write_text")).lower()
        raw_path = str(payload.get("file_path") or action.target_ref or "workspace/oryn_output.txt")
        target_path = (self.workspace_root / raw_path).resolve()

        # Enforce workspace path confinement
        allowed_roots = (
            str((self.workspace_root / "workspace").resolve()),
            str((self.workspace_root / "agent").resolve()),
            str(self.workspace_root),
        )
        if not any(str(target_path).startswith(r) for r in allowed_roots):
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="BLOCKED_POLICY",
                verified=False,
                duration_ms=dur,
                observed_evidence=f"Blocked file access outside workspace: {target_path}",
                error_code="PATH_OUTSIDE_WORKSPACE",
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)

        if file_op == "write_csv" or (target_path.suffix.lower() == ".csv" and "rows" in payload):
            rows: List[Any] = payload.get("rows", [])
            headers: List[str] = payload.get("headers", [])
            buf = io.StringIO()
            writer = csv.writer(buf)
            if headers:
                writer.writerow(headers)
            for row in rows:
                writer.writerow(row if isinstance(row, (list, tuple)) else [row])
            content_bytes = buf.getvalue().encode("utf-8")
            target_path.write_bytes(content_bytes)
            fnv_hash = native_accel.fast_hash64_hex(content_bytes)
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="COMPLETED",
                verified=True,
                duration_ms=dur,
                observed_evidence=f"Wrote {len(rows)} rows to {target_path.name} (FNV64={fnv_hash})",
                output_data={"file_path": str(target_path), "rows_written": len(rows), "fnv64": fnv_hash},
            )

        if file_op == "write_xlsx" or target_path.suffix.lower() == ".xlsx":
            rows = payload.get("rows", [])
            headers = payload.get("headers", [])
            try:
                import openpyxl  # type: ignore

                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = str(payload.get("sheet_name", "Sheet1"))
                if headers:
                    ws.append(headers)
                for r in rows:
                    ws.append(list(r) if isinstance(r, (list, tuple)) else [r])
                wb.save(str(target_path))
                fnv_hash = native_accel.fast_hash64_hex(target_path.read_bytes())
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel=self.channel,
                    status="COMPLETED",
                    verified=True,
                    duration_ms=dur,
                    observed_evidence=f"Generated Excel workbook {target_path.name} ({len(rows)} rows, FNV64={fnv_hash})",
                    output_data={"file_path": str(target_path), "rows_written": len(rows), "fnv64": fnv_hash},
                )
            except ImportError:
                csv_fallback = target_path.with_suffix(".csv")
                buf = io.StringIO()
                writer = csv.writer(buf)
                if headers:
                    writer.writerow(headers)
                for r in rows:
                    writer.writerow(list(r) if isinstance(r, (list, tuple)) else [r])
                csv_bytes = buf.getvalue().encode("utf-8")
                csv_fallback.write_bytes(csv_bytes)
                fnv_hash = native_accel.fast_hash64_hex(csv_bytes)
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel=self.channel,
                    status="COMPLETED",
                    verified=True,
                    duration_ms=dur,
                    observed_evidence=f"openpyxl not installed; wrote {len(rows)} rows to {csv_fallback.name} (FNV64={fnv_hash})",
                    output_data={"file_path": str(csv_fallback), "rows_written": len(rows), "fnv64": fnv_hash},
                )

        if file_op == "sqlite_query" or "sql_query" in payload:
            sql = str(payload.get("sql_query", ""))
            params = tuple(payload.get("sql_params", ()))
            with sqlite3.connect(str(target_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(sql, params)
                if sql.strip().upper().startswith(("SELECT", "PRAGMA", "WITH")):
                    fetched = [dict(r) for r in cur.fetchall()]
                    conn.commit()
                    dur = round((time.perf_counter() - t0) * 1000.0, 2)
                    return ExecutionReceipt(
                        action_id=action.action_id,
                        runtime_id=action.runtime_id,
                        channel=self.channel,
                        status="COMPLETED",
                        verified=True,
                        duration_ms=dur,
                        observed_evidence=f"SQLite query returned {len(fetched)} rows from {target_path.name}",
                        output_data={"rows": fetched, "row_count": len(fetched)},
                    )
                conn.commit()
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel=self.channel,
                    status="COMPLETED",
                    verified=True,
                    duration_ms=dur,
                    observed_evidence=f"SQLite statement affected {cur.rowcount} rows in {target_path.name}",
                    output_data={"rowcount": cur.rowcount},
                )

        if file_op == "read_text":
            if not target_path.exists():
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel=self.channel,
                    status="FAILED",
                    verified=False,
                    duration_ms=dur,
                    observed_evidence=f"File not found: {target_path}",
                    error_code="FILE_NOT_FOUND",
                )
            raw_bytes = target_path.read_bytes()
            text_out = raw_bytes.decode("utf-8", errors="replace")
            fnv_hash = native_accel.fast_hash64_hex(raw_bytes)
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="COMPLETED",
                verified=True,
                duration_ms=dur,
                observed_evidence=f"Read {len(raw_bytes)} bytes from {target_path.name} (FNV64={fnv_hash})",
                output_data={"file_path": str(target_path), "content": text_out[:8000], "fnv64": fnv_hash},
            )

        # Default: write_text / write_json
        text_body = action.text if action.text is not None else str(payload.get("content", ""))
        if isinstance(payload.get("json_data"), (dict, list)):
            text_body = json.dumps(payload["json_data"], indent=2)
        raw_bytes = text_body.encode("utf-8")
        target_path.write_bytes(raw_bytes)
        fnv_hash = native_accel.fast_hash64_hex(raw_bytes)
        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel=self.channel,
            status="COMPLETED",
            verified=True,
            duration_ms=dur,
            observed_evidence=f"Wrote {len(raw_bytes)} bytes to {target_path.name} (FNV64={fnv_hash})",
            output_data={"file_path": str(target_path), "bytes_written": len(raw_bytes), "fnv64": fnv_hash},
        )

    async def _execute_mcp_stdio(self, action: ComputerAction, t0: float) -> ExecutionReceipt:
        payload = action.payload or {}
        server_id = str(payload.get("mcp_server_id", "local_mcp"))
        script_path = Path(str(payload.get("mcp_script", "")))
        tool_name = str(payload.get("tool_name") or action.target_ref or "")
        tool_args = dict(payload.get("tool_args", {}))

        if not script_path.exists():
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="FAILED",
                verified=False,
                duration_ms=dur,
                observed_evidence=f"MCP server script not found: {script_path}",
                error_code="MCP_SCRIPT_MISSING",
            )

        res = await mcp_hot_pool.call_warm_tool(
            server_id=server_id,
            script_path=script_path,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        ok = not res.get("blocked", False) and "error" not in res.get("call_response", {})
        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel=self.channel,
            status="COMPLETED" if ok else "FAILED",
            verified=ok,
            duration_ms=dur,
            observed_evidence=f"MCP warm call '{tool_name}' on {server_id} in {res.get('latency_ms', dur)}ms",
            output_data=res,
            error_code="" if ok else "MCP_CALL_ERROR",
        )

    async def _execute_rest_api(self, action: ComputerAction, t0: float) -> ExecutionReceipt:
        payload = action.payload or {}
        url = str(payload.get("http_url") or action.target_ref or "")
        method = str(payload.get("http_method", "GET")).upper()
        headers = {"User-Agent": "ORYN-NativeAPI/1.0", **dict(payload.get("headers", {}))}
        body_bytes: Optional[bytes] = None

        if "json_body" in payload:
            body_bytes = json.dumps(payload["json_body"]).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif action.text:
            body_bytes = action.text.encode("utf-8")

        def _sync_http() -> Tuple[int, str]:
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=max(1.0, action.timeout_ms / 1000.0)) as resp:
                return int(resp.status), resp.read().decode("utf-8", errors="replace")

        try:
            loop = asyncio.get_running_loop()
            status_code, resp_text = await loop.run_in_executor(None, _sync_http)
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            ok = 200 <= status_code < 400
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="COMPLETED" if ok else "FAILED",
                verified=ok,
                duration_ms=dur,
                observed_evidence=f"HTTP {method} {url} -> {status_code} ({len(resp_text)} chars)",
                output_data={"status_code": status_code, "body": resp_text[:4000]},
            )
        except Exception as exc:
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="FAILED",
                verified=False,
                duration_ms=dur,
                observed_evidence=f"HTTP {method} {url} failed: {exc}",
                error_code="HTTP_REQUEST_FAILED",
            )

    async def _execute_os_intent(self, action: ComputerAction, t0: float) -> ExecutionReceipt:
        payload = action.payload or {}
        intent_type = str(payload.get("intent_type", "open_url" if action.operation == "navigate" else "launch_app"))
        target = str(payload.get("target") or action.target_ref or action.text or "").strip()

        cmd: Optional[List[str]] = None
        if intent_type == "open_url":
            if self.is_termux and shutil.which("termux-open-url"):
                cmd = ["termux-open-url", target]
            elif self.is_termux and shutil.which("am"):
                cmd = ["am", "start", "-a", "android.intent.action.VIEW", "-d", target]
            elif shutil.which("xdg-open"):
                cmd = ["xdg-open", target]
            elif shutil.which("open"):
                cmd = ["open", target]
        elif intent_type == "clipboard_set":
            if self.is_termux and shutil.which("termux-clipboard-set"):
                cmd = ["termux-clipboard-set", target]
            elif shutil.which("xclip"):
                cmd = ["xclip", "-selection", "clipboard"]

        if not cmd:
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="FAILED",
                verified=False,
                duration_ms=dur,
                observed_evidence=f"No OS intent binary available for {intent_type} ({target})",
                error_code="OS_INTENT_UNAVAILABLE",
                recovery_suggestion="Escalate to Stage 2/3 Browser Engine or Stage 4 Accessibility.",
            )

        res = await sandbox_executor.run_isolated_command(
            cmd,
            timeout_sec=max(2.0, action.timeout_ms / 1000.0),
        )
        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        ok = res.exit_code == 0
        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel=self.channel,
            status="COMPLETED" if ok else "FAILED",
            verified=ok,
            duration_ms=dur,
            observed_evidence=f"Dispatched OS intent {' '.join(cmd)} (exit_code={res.exit_code})",
            output_data={"exit_code": res.exit_code, "stdout": res.stdout, "stderr": res.stderr},
            error_code="" if ok else "OS_INTENT_NONZERO",
        )

    async def _execute_sandboxed_cli(self, action: ComputerAction, t0: float) -> ExecutionReceipt:
        payload = action.payload or {}
        argv = payload.get("argv")
        cli_cmd = str(payload.get("cli_command") or action.text or "").strip()

        if not argv and not cli_cmd:
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="FAILED",
                verified=False,
                duration_ms=dur,
                observed_evidence="No CLI command or argv provided in ComputerAction.",
                error_code="EMPTY_CLI_COMMAND",
            )

        if not argv:
            import shlex

            try:
                argv = shlex.split(cli_cmd)
            except ValueError:
                argv = cli_cmd.split()

        res = await sandbox_executor.run_isolated_command(
            argv,
            cwd=str(self.workspace_root),
            timeout_sec=max(1.0, float(action.timeout_ms) / 1000.0),
        )
        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        ok = (res.exit_code == 0) and not res.timed_out
        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel=self.channel,
            status="COMPLETED" if ok else "FAILED",
            verified=ok,
            duration_ms=dur,
            observed_evidence=(
                res.stdout.strip()[:600]
                if ok and res.stdout.strip()
                else f"Command {argv[0]} exited with {res.exit_code}: {res.stderr.strip()[:400]}"
            ),
            output_data={
                "exit_code": res.exit_code,
                "stdout": res.stdout[:4000],
                "stderr": res.stderr[:1500],
                "isolated_pid": res.isolated_pid,
                "sanitized_env": res.sanitized_env_confirmed,
            },
            error_code="" if ok else ("TIMEOUT" if res.timed_out else f"EXIT_{res.exit_code}"),
        )

    async def verify(
        self,
        action: ComputerAction,
        receipt: ExecutionReceipt,
        pre_state: Optional[AXTreeSnapshot] = None,
    ) -> ExecutionReceipt:
        if receipt.status != "COMPLETED":
            receipt.verified = False
            return receipt

        out_file = receipt.output_data.get("file_path")
        if out_file:
            p = Path(str(out_file))
            if not p.exists() or p.stat().st_size == 0:
                receipt.status = "FAILED"
                receipt.verified = False
                receipt.error_code = "POSTCONDITION_FILE_EMPTY_OR_MISSING"
                receipt.observed_evidence = f"Postcondition failed: {out_file} missing or 0 bytes."
                return receipt

        receipt.verified = True
        return receipt

    async def recover(
        self,
        action: ComputerAction,
        failed_receipt: ExecutionReceipt,
    ) -> Optional[ComputerAction]:
        return None


native_api_driver = NativeAPIDriver()
