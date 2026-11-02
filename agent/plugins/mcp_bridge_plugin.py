from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.plugin_host import Action, ActionResult, AuthorizedTaskContext, Capability, VerificationResult
from agent.kernel.sandbox_isolation import sandbox_executor


class MCPClientBridgePlugin:
    """Verified Model Context Protocol (MCP) Multi-Server Client Bridge with
    Cryptographic SHA-256 Server Allowlisting, Namespace Confinement & Sanitized Stdio Jail.
    """

    plugin_id = "plugin.mcp_bridge"
    api_version = "2026-07-28"
    DB_PATH = Path("workspace/kernel_governance.db")
    DEFAULT_STDIO_SERVER = Path("workspace/jev_stdio_mcp_server.py")

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.learned_mcp_tools: Dict[str, Dict[str, Any]] = {}
        self._init_db()
        self.register_verified_mcp_server(
            server_id="jev-verified-stdio-mcp",
            script_path=self.DEFAULT_STDIO_SERVER,
            allowed_namespaces=["github.", "sqlite.", "filesystem."],
        )

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_mcp_servers (
                    server_id TEXT PRIMARY KEY,
                    script_path TEXT NOT NULL,
                    sha256_fingerprint TEXT NOT NULL,
                    allowed_namespaces_json TEXT NOT NULL,
                    verified_by_kernel INTEGER NOT NULL,
                    registered_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def register_verified_mcp_server(
        self,
        server_id: str,
        script_path: str | Path,
        allowed_namespaces: List[str],
    ) -> Dict[str, Any]:
        p = Path(script_path).resolve()
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "missing"
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO verified_mcp_servers (
                    server_id, script_path, sha256_fingerprint, allowed_namespaces_json, verified_by_kernel, registered_at
                ) VALUES (?, ?, ?, ?, 1, ?)
                """,
                (server_id, str(p), sha, json.dumps(allowed_namespaces), time.time()),
            )
            conn.commit()
        return {"server_id": server_id, "sha256_fingerprint": sha[:16], "verified": True}

    def verify_server_before_spawn(self, server_id: str, script_path: str | Path) -> Dict[str, Any]:
        """Strict Security Gate: Rejects unverified MCP servers or scripts whose SHA-256 hash was modified."""
        p = Path(script_path).resolve()
        if not p.exists():
            return {"allowed": False, "status": "BLOCKED_MCP_BINARY_MISSING", "reason": f"MCP server '{p}' does not exist."}
        current_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM verified_mcp_servers WHERE server_id = ?", (server_id,)).fetchone()
            if not row or not row["verified_by_kernel"]:
                return {"allowed": False, "status": "BLOCKED_UNVERIFIED_MCP_SERVER", "reason": f"MCP server '{server_id}' is not in the verified allowlist."}
            if row["sha256_fingerprint"] != current_sha or row["script_path"] != str(p):
                return {"allowed": False, "status": "BLOCKED_MCP_HASH_MISMATCH", "reason": f"MCP server '{server_id}' binary/script hash mismatch (tampering detected)."}
            return {
                "allowed": True,
                "status": "VERIFIED_MCP_SERVER",
                "sha256_fingerprint": current_sha[:16],
                "allowed_namespaces": json.loads(row["allowed_namespaces_json"]),
            }

    def discover_capabilities(self) -> List[Capability]:
        return [
            Capability(
                id="mcp.tool_invoke",
                version="3.0.0",
                plugin_id=self.plugin_id,
                description="Spawns verified, SHA256-pinned MCP servers over isolated JSON-RPC 2.0 stdio pipes.",
                execution_backend="OFFICIAL_API",
                risk_class="read",
                data_sensitivity="PROJECT",
                preconditions=["mcp_server_verified_sha256", "jsonrpc_schema_valid"],
                postconditions=["mcp_jsonrpc_result_verified", "output_taint_tagged"],
            ),
        ]

    def health_check(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "status": "HEALTHY",
            "transport": "JSONRPC_2.0_STDIO_SANDBOXED",
            "learned_tools_count": len(self.learned_mcp_tools),
        }

    async def execute_stdio_mcp_session(
        self,
        server_id: str,
        script_path: str | Path,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> Dict[str, Any]:
        sec_check = self.verify_server_before_spawn(server_id, script_path)
        if not sec_check["allowed"]:
            return {
                "blocked": True,
                "security_status": sec_check["status"],
                "reason": sec_check["reason"],
                "discovered_tools": [],
                "call_response": {"jsonrpc": "2.0", "id": 3, "error": {"code": -32001, "message": sec_check["reason"]}},
                "isolated_pid": -1,
                "sanitized_env": True,
            }

        allowed_ns = sec_check.get("allowed_namespaces", [])
        if not any(tool_name.startswith(ns) for ns in allowed_ns):
            return {
                "blocked": True,
                "security_status": "BLOCKED_MCP_TOOL_NAMESPACE",
                "reason": f"Tool '{tool_name}' is outside allowed namespaces {allowed_ns} for server '{server_id}'.",
                "discovered_tools": [],
                "call_response": {"jsonrpc": "2.0", "id": 3, "error": {"code": -32002, "message": "Namespace violation"}},
                "isolated_pid": -1,
                "sanitized_env": True,
            }

        from agent.kernel.fast_players import mcp_hot_pool

        warm_res = await mcp_hot_pool.call_warm_tool(
            server_id=server_id,
            script_path=script_path,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        for t_name in warm_res["discovered_tools"]:
            self.learned_mcp_tools[f"mcp.{t_name}"] = {"name": t_name, "server": server_id}

        return {
            "blocked": False,
            "security_status": "VERIFIED_MCP_SERVER",
            "sha256_fingerprint": sec_check["sha256_fingerprint"],
            "warm_pool_hit": warm_res["warm_pool_hit"],
            "latency_ms": warm_res["latency_ms"],
            "discovered_tools": warm_res["discovered_tools"],
            "call_response": warm_res["call_response"],
            "isolated_pid": warm_res["isolated_pid"],
            "sanitized_env": warm_res["sanitized_env"],
        }

    async def execute(self, action: Action, context: AuthorizedTaskContext) -> ActionResult:
        prompt = action.raw_instruction
        server_id = action.validated_arguments.get("mcp_server_id", "jev-verified-stdio-mcp")
        script_path = action.validated_arguments.get("mcp_script_path", str(self.DEFAULT_STDIO_SERVER))
        tool_name = action.validated_arguments.get("mcp_tool_name", "github.analyze_repo_issues")

        repo_m = re.search(r"(?:for|in)\s+([a-zA-Z0-9_\-/]+)", prompt)
        repo = repo_m.group(1) if repo_m else "langchain-ai/langchain"

        session = await self.execute_stdio_mcp_session(
            server_id=server_id,
            script_path=script_path,
            tool_name=tool_name,
            tool_args={"repo": repo},
        )
        if session.get("blocked"):
            raw_err = {
                "intent": "MCP_TOOL_CALL_BLOCKED",
                "security_status": session["security_status"],
                "spoken_response": f"MCP Security Gate Blocked Execution ({session['security_status']}): {session['reason']}",
            }
            return ActionResult(
                action_id=action.action_id,
                capability_id=action.capability_id,
                status="FAILED",
                raw_Legacy_dict=raw_err,
                error_code=session["security_status"],
            )

        rpc_response = session["call_response"]
        content_blocks = rpc_response.get("result", {}).get("content", [])
        text_out = content_blocks[0]["text"] if content_blocks else "No MCP content."

        raw = {
            "intent": "MCP_TOOL_CALL",
            "mcp_server": server_id,
            "mcp_transport": "STDIO_JSONRPC_2.0",
            "server_sha256": session["sha256_fingerprint"],
            "isolated_pid": session["isolated_pid"],
            "sanitized_env": session["sanitized_env"],
            "discovered_tools": session["discovered_tools"],
            "jsonrpc_response": rpc_response,
            "taint_level": "UNTRUSTED_EXTERNAL",
            "spoken_response": f"{text_out} (Discovered {len(session['discovered_tools'])} MCP tools via isolated stdio PID={session['isolated_pid']}).",
        }
        return ActionResult(
            action_id=action.action_id,
            capability_id=action.capability_id,
            status="COMPLETED",
            raw_Legacy_dict=raw,
            provider_receipt=f"mcp_stdio:{server_id}:pid={session['isolated_pid']}:sha={session['sha256_fingerprint']}",
        )

    def verify(self, action: Action, result: ActionResult) -> VerificationResult:
        raw = result.raw_Legacy_dict
        if result.status == "FAILED":
            return VerificationResult(
                action_id=action.action_id,
                capability_id=action.capability_id,
                status="FAILED",
                verified=False,
                evidence_type="MCP_SECURITY_GATE",
                observed_evidence=raw.get("spoken_response", "MCP call blocked"),
            )
        rpc = raw.get("jsonrpc_response", {})
        ok = (
            rpc.get("jsonrpc") == "2.0"
            and not rpc.get("result", {}).get("isError", True)
            and raw.get("sanitized_env") is True
            and len(raw.get("discovered_tools", [])) >= 1
        )
        return VerificationResult(
            action_id=action.action_id,
            capability_id=action.capability_id,
            status="COMPLETED" if ok else "FAILED",
            verified=ok,
            evidence_type="MCP_STDIO_JSONRPC_VERIFIED",
            observed_evidence=f"Stdio JSON-RPC 2.0 verified (PID={raw.get('isolated_pid')}, SHA={raw.get('server_sha256')}, Tools={raw.get('discovered_tools')})",
        )
