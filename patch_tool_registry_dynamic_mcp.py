from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Update imports
if "from agent.pa_scaffolder.dynamic_mcp import DynamicMCPHub" not in code:
    code = "from agent.pa_scaffolder.dynamic_mcp import DynamicMCPHub, MCPServerConfig\n" + code

# 2. Replace static mcp_clients dictionary in __init__ with DynamicMCPHub
old_init_str = "self.mcp_clients: Dict[str, StdioMCPClient] = {}"
new_init_str = "self.mcp_hub = DynamicMCPHub(idle_ttl_sec=45.0)"

if old_init_str in code:
    code = code.replace(old_init_str, new_init_str)
elif "self.mcp_hub" not in code:
    anchor = "self.github = GitHubEngine(workspace_root=self.workspace_root)"
    code = code.replace(anchor, anchor + "\n        self.mcp_hub = DynamicMCPHub(idle_ttl_sec=45.0)")

# 3. Update close() method to shut down active MCP servers cleanly
old_close = "    def close(self):"
new_close = """    def close(self):
        if hasattr(self, "mcp_hub") and self.mcp_hub:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.mcp_hub.shutdown_all())
            except Exception:
                pass"""

if "self.mcp_hub.shutdown_all()" not in code:
    code = code.replace(old_close, new_close)

# 4. Update dispatch handling for dynamic MCP calls
old_mcp_dispatch = '            elif tool_name == "mcp_connect":'
new_mcp_dispatch = """            # -----------------------------------------------------------------
            # Dynamic On-Demand MCP Execution (Controlled by Jev)
            # -----------------------------------------------------------------
            elif tool_name == "mcp_call":
                s_id = args.get("server_id", "")
                t_name = args.get("tool_name", "")
                t_args = args.get("arguments", {})
                user_context = args.get("user_prompt", "")

                # If server_id is omitted, Jev matches the server dynamically from the query
                if not s_id and user_context:
                    s_id = self.mcp_hub.match_server_by_intent(user_context)

                if not s_id:
                    return ToolResult(tool_name=tool_name, success=False, error="No matching MCP server found for this task.")

                ok, res_text = await self.mcp_hub.dispatch_tool(s_id, t_name, t_args)
                return ToolResult(tool_name=tool_name, success=ok, output=res_text, error=None if ok else res_text)

            elif tool_name == "mcp_list_tools":
                s_id = args.get("server_id", "")
                ok, srv, msg = await self.mcp_hub.get_or_spawn_server(s_id)
                if not ok or not srv:
                    return ToolResult(tool_name=tool_name, success=False, error=msg)
                tools_desc = [f"{t.name}: {t.description}" for t in srv.tools.values()]
                return ToolResult(tool_name=tool_name, success=True, output="\\n".join(tools_desc) if tools_desc else "No tools found.")

            elif tool_name == "mcp_connect":"""

if "tool_name == \"mcp_list_tools\"" not in code and old_mcp_dispatch in code:
    code = code.replace(old_mcp_dispatch, new_mcp_dispatch)

target.write_text(code, encoding="utf-8")
print("[✓] Integrated DynamicMCPHub into tool_registry.py")
