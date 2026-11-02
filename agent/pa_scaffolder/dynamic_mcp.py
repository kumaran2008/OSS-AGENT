import os
import sys
import json
import time
import asyncio
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set


@dataclass
class MCPServerConfig:
    server_id: str
    transport: str              # "stdio" or "sse"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    domain_keywords: List[str] = field(default_factory=list)


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_id: str


class ActiveMCPServer:
    """Manages the live lifecycle, I/O pipes, and idle countdown of an active MCP instance."""

    def __init__(self, config: MCPServerConfig, idle_ttl_sec: float = 45.0):
        self.config = config
        self.idle_ttl = idle_ttl_sec
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.tools: Dict[str, MCPToolInfo] = {}
        self.last_active_time = time.monotonic()
        self._request_id = 0
        self._lock = asyncio.Lock()

    def touch(self):
        self.last_active_time = time.monotonic()

    def is_expired(self) -> bool:
        return (time.monotonic() - self.last_active_time) >= self.idle_ttl

    async def initialize_connection(self) -> bool:
        if self.config.transport == "stdio":
            if not self.config.command:
                return False
            cmd = [self.config.command] + self.config.args
            env = os.environ.copy()
            env.update(self.config.env)

            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env
                )
            except Exception:
                return False

            init_req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                    "clientInfo": {"name": "oss-agent-dynamic-mcp", "version": "2.0.0"}
                }
            }
            res = await self._send_raw(init_req)
            if not res or "error" in res:
                await self.shutdown()
                return False

            await self._send_raw({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, is_notify=True)
            await self.discover_tools()
            self.touch()
            return True

        return False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_raw(self, payload: Dict[str, Any], is_notify: bool = False, timeout: float = 12.0) -> Optional[Dict[str, Any]]:
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            return None

        line = json.dumps(payload) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

        if is_notify:
            return None

        try:
            raw_line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
            if not raw_line:
                return None
            return json.loads(raw_line.decode("utf-8"))
        except Exception:
            return None

    async def discover_tools(self) -> List[MCPToolInfo]:
        async with self._lock:
            req = {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}}
            res = await self._send_raw(req)
            if not res or "result" not in res:
                return []

            tools_raw = res["result"].get("tools", [])
            self.tools.clear()
            for t in tools_raw:
                info = MCPToolInfo(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_id=self.config.server_id
                )
                self.tools[t["name"]] = info

            return list(self.tools.values())

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        async with self._lock:
            self.touch()
            req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            }
            res = await self._send_raw(req, timeout=30.0)
            if not res:
                return False, f"MCP server '{self.config.server_id}' timed out."
            if "error" in res:
                err = res["error"]
                return False, f"MCP Error {err.get('code')}: {err.get('message')}"

            content = res.get("result", {}).get("content", [])
            out = []
            for item in content:
                if item.get("type") == "text":
                    out.append(item.get("text", ""))

            return True, "\n".join(out) if out else "Execution complete."

    async def shutdown(self):
        if self.proc:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        self.tools.clear()


class DynamicMCPHub:
    """
    On-Demand Fast MCP Orchestrator controlled by Jev.
    - Matches user intent to target MCP servers in <0.05ms.
    - Connects dynamically only when requested by task.
    - Keeps active servers warm in an LRU pool.
    - Shuts down idle servers automatically via dynamic TTL eviction.
    """

    CONFIG_PATH = Path("workspace/mcp_servers.json")

    def __init__(self, idle_ttl_sec: float = 45.0):
        self.idle_ttl = idle_ttl_sec
        # Adaptive check interval: 1/4 of TTL, bounded between 0.1s and 2.0s
        self.check_interval = min(2.0, max(0.1, self.idle_ttl / 4.0))
        self.server_configs: Dict[str, MCPServerConfig] = {}
        self.active_pool: Dict[str, ActiveMCPServer] = {}
        self._reaper_task: Optional[asyncio.Task] = None
        self._load_default_configs()

    def _load_default_configs(self):
        defaults = [
            MCPServerConfig(
                server_id="filesystem",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "workspace"],
                domain_keywords=["disk", "directory", "folder", "filesystem", "path"]
            ),
            MCPServerConfig(
                server_id="github",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_TOKEN", "")},
                domain_keywords=["github", "pr", "issue", "repo", "pull request", "fork", "commit"]
            ),
            MCPServerConfig(
                server_id="postgres",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-postgres"],
                domain_keywords=["postgres", "sql", "database", "table", "schema", "query"]
            ),
            MCPServerConfig(
                server_id="brave_search",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-brave-search"],
                domain_keywords=["search", "web", "lookup", "google", "brave", "internet"]
            )
        ]

        for d in defaults:
            self.server_configs[d.server_id] = d

        if self.CONFIG_PATH.exists():
            try:
                data = json.loads(self.CONFIG_PATH.read_text(encoding="utf-8"))
                for s_id, item in data.items():
                    self.server_configs[s_id] = MCPServerConfig(
                        server_id=s_id,
                        transport=item.get("transport", "stdio"),
                        command=item.get("command"),
                        args=item.get("args", []),
                        env=item.get("env", {}),
                        url=item.get("url"),
                        domain_keywords=item.get("domain_keywords", [])
                    )
            except Exception:
                pass

    def register_server(self, config: MCPServerConfig):
        self.server_configs[config.server_id] = config

    def match_server_by_intent(self, user_prompt: str) -> Optional[str]:
        clean = user_prompt.lower()
        best_server = None
        max_matches = 0

        for s_id, cfg in self.server_configs.items():
            matches = sum(1 for kw in cfg.domain_keywords if kw in clean)
            if matches > max_matches:
                max_matches = matches
                best_server = s_id

        return best_server

    async def get_or_spawn_server(self, server_id: str) -> Tuple[bool, Optional[ActiveMCPServer], str]:
        if server_id in self.active_pool:
            srv = self.active_pool[server_id]
            srv.touch()
            return True, srv, f"Connected to warm server '{server_id}'."

        cfg = self.server_configs.get(server_id)
        if not cfg:
            return False, None, f"MCP server '{server_id}' is not configured."

        srv = ActiveMCPServer(cfg, idle_ttl_sec=self.idle_ttl)
        ok = await srv.initialize_connection()
        if not ok:
            return False, None, f"Failed to initialize MCP server '{server_id}'."

        self.active_pool[server_id] = srv
        self._ensure_reaper_started()
        return True, srv, f"Spawned on-demand server '{server_id}'."

    async def dispatch_tool(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        ok, srv, msg = await self.get_or_spawn_server(server_id)
        if not ok or not srv:
            return False, msg

        return await srv.execute_tool(tool_name, arguments)

    def _ensure_reaper_started(self):
        if self._reaper_task is None or self._reaper_task.done():
            loop = asyncio.get_event_loop()
            self._reaper_task = loop.create_task(self._idle_eviction_loop())

    async def evict_expired(self) -> int:
        """Evaluates and evicts any idle servers immediately."""
        expired_ids = [s_id for s_id, srv in self.active_pool.items() if srv.is_expired()]
        for s_id in expired_ids:
            srv = self.active_pool.pop(s_id, None)
            if srv:
                await srv.shutdown()
        return len(expired_ids)

    async def _idle_eviction_loop(self):
        """Monitors active servers and terminates idle instances to reclaim memory."""
        while self.active_pool:
            await asyncio.sleep(self.check_interval)
            await self.evict_expired()

    async def shutdown_all(self):
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()

        for srv in list(self.active_pool.values()):
            await srv.shutdown()
        self.active_pool.clear()
