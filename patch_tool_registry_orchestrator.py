from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Import WorkspaceOrchestrator
if "from agent.pa_scaffolder.workspace_orchestrator import WorkspaceOrchestrator" not in code:
    code = "from agent.pa_scaffolder.workspace_orchestrator import WorkspaceOrchestrator\n" + code

# 2. Add orchestrator to __init__
old_init_anchor = "self.symbol_mapper = RepoSymbolMapper(workspace_root=str(self.workspace_root))"
new_init_anchor = old_init_anchor + "\n        self.orchestrator = WorkspaceOrchestrator(self.workspace_root)"

if old_init_anchor in code and "self.orchestrator =" not in code:
    code = code.replace(old_init_anchor, new_init_anchor)

# 3. Add dispatch handlers
dispatch_anchor = '            # -----------------------------------------------------------------\n            # GitHub End-to-End Suite'
new_dispatch_cases = """            # -----------------------------------------------------------------
            # Workspace Surface & Health Probing Tools
            # -----------------------------------------------------------------
            if tool_name == "workspace_open_editor":
                rel_f = args.get("file_path", "")
                line = int(args.get("line_number", 1))
                ok, msg = self.orchestrator.open_in_editor(rel_f, line)
                return ToolResult(tool_name=tool_name, success=ok, output=msg)

            elif tool_name == "workspace_probe_port":
                port = int(args.get("port", 8000))
                host = args.get("host", "127.0.0.1")
                path = args.get("path", "/")
                timeout = float(args.get("timeout_sec", 6.0))
                ok, msg = self.orchestrator.probe_service_health(port, host, path, timeout)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

            elif tool_name == "workspace_atomic_patch":
                manifest = args.get("patches", {})
                ok, msg, touched = self.orchestrator.atomic_multi_file_patch(manifest)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

"""

if "workspace_open_editor" not in code and dispatch_anchor in code:
    code = code.replace(dispatch_anchor, new_dispatch_cases + dispatch_anchor)

# 4. Add schemas to get_all_tool_schemas
schema_anchor = '            {"type": "function", "function": {"name": "mcp_call",'
new_schemas = """            {"type": "function", "function": {"name": "workspace_open_editor", "description": "Opens the specified file in the user's active editor (Cursor/VSCode) on desktop, or signals focus in terminal", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "line_number": {"type": "integer"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "workspace_probe_port", "description": "Probes if a local development server is listening on a port and returning valid responses", "parameters": {"type": "object", "properties": {"port": {"type": "integer"}, "host": {"type": "string"}, "path": {"type": "string"}, "timeout_sec": {"type": "number"}}, "required": ["port"]}}},
"""

if "workspace_open_editor" not in code and schema_anchor in code:
    code = code.replace(schema_anchor, new_schemas + schema_anchor)

target.write_text(code, encoding="utf-8")
print("[✓] Registered Workspace Orchestrator tools in tool_registry.py")
