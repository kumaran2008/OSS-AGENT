import json
import asyncio
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class MCPToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str


class StdioMCPClient:
    """
    Production-grade Model Context Protocol (MCP) JSON-RPC 2.0 Client.
    Connects to external MCP servers over stdio, discovers tools,
    and executes tool invocations dynamically.
    """

    def __init__(self, server_name: str, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        self.server_name = server_name
        self.command = command
        self.args = args
        self.env = env or {}
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self.discovered_tools: Dict[str, MCPToolDefinition] = {}

    async def start(self) -> bool:
        """Launches the MCP server subprocess and completes protocol initialization."""
        try:
            cmd = [self.command] + self.args
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )

            # Send MCP 'initialize' handshake
            init_payload = {
                "jsonrpc": "2.0",
                "id": self._get_next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "oss-agent", "version": "1.0.0"}
                }
            }
            resp = await self._send_request(init_payload)
            if not resp or "error" in resp:
                return False

            # Send initialized notification
            notify = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            await self._send_notification(notify)

            # Discover available tools
            await self.refresh_tools()
            return True
        except Exception:
            return False

    def _get_next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(self, payload: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            return None
        line = json.dumps(payload) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

        try:
            raw_resp = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
            if not raw_resp:
                return None
            return json.loads(raw_resp.decode("utf-8"))
        except Exception:
            return None

    async def _send_notification(self, payload: Dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            return
        line = json.dumps(payload) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

    async def refresh_tools(self) -> List[MCPToolDefinition]:
        """Queries the MCP server for registered tools via 'tools/list'."""
        req = {"jsonrpc": "2.0", "id": self._get_next_id(), "method": "tools/list", "params": {}}
        resp = await self._send_request(req)
        if not resp or "result" not in resp:
            return []

        tools_data = resp["result"].get("tools", [])
        self.discovered_tools.clear()
        for t in tools_data:
            tool_def = MCPToolDefinition(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.server_name
            )
            self.discovered_tools[t["name"]] = tool_def

        return list(self.discovered_tools.values())

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        """Dispatches tool execution to the MCP server via 'tools/call'."""
        req = {
            "jsonrpc": "2.0",
            "id": self._get_next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments}
        }
        resp = await self._send_request(req, timeout=30.0)
        if not resp:
            return False, "MCP server timed out or disconnected."
        if "error" in resp:
            return False, f"MCP Error {resp['error'].get('code')}: {resp['error'].get('message')}"

        content_list = resp.get("result", {}).get("content", [])
        output_chunks = []
        for item in content_list:
            if item.get("type") == "text":
                output_chunks.append(item.get("text", ""))

        return True, "\n".join(output_chunks) if output_chunks else "Tool execution completed."

    async def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                await self.proc.wait()
            except Exception:
                pass
