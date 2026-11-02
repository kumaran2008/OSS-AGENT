from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add imports
imports_to_add = """from agent.pa_scaffolder.github_engine import GitHubEngine
from agent.pa_scaffolder.mcp_client import StdioMCPClient
"""
if "from agent.pa_scaffolder.github_engine import" not in code:
    code = imports_to_add + code

# 2. Add instances to __init__
init_anchor = "self.symbol_mapper = RepoSymbolMapper(workspace_root=str(self.workspace_root))"
new_init = init_anchor + """
        self.github = GitHubEngine(workspace_root=self.workspace_root)
        self.mcp_clients: Dict[str, StdioMCPClient] = {}"""

if init_anchor in code and "self.github =" not in code:
    code = code.replace(init_anchor, new_init)

# 3. Add dispatch handlers for GitHub and MCP
dispatch_anchor = '            # 1. Terminal PTY Execution'
github_mcp_dispatch = """            # -----------------------------------------------------------------
            # GitHub End-to-End Suite
            # -----------------------------------------------------------------
            if tool_name == "github_clone_or_fork":
                repo = args.get("repo", "")
                do_fork = bool(args.get("fork", False))
                ok, msg, pth = self.github.clone_or_fork(repo, do_fork=do_fork)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

            elif tool_name == "github_list_issues":
                repo = args.get("repo", "")
                limit = int(args.get("limit", 5))
                ok, issues, msg = self.github.list_issues(repo, limit=limit)
                if not ok:
                    return ToolResult(tool_name=tool_name, success=False, error=msg)
                summaries = [self.github.get_issue_summary(iss) for iss in issues]
                return ToolResult(
                    tool_name=tool_name,
                    success=True,
                    output="\\n\\n".join(summaries) if summaries else "No open issues found."
                )

            elif tool_name == "github_create_pr":
                repo_name = args.get("repo_name", "")
                branch = args.get("branch", f"fix/agent-{int(asyncio.get_event_loop().time())}")
                title = args.get("title", "Automated bugfix")
                body = args.get("body", "Resolved autonomously by agent.")
                repo_path = self.github.repos_dir / repo_name
                ok, msg = self.github.create_pull_request(repo_path, branch, title, body)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

            # -----------------------------------------------------------------
            # Model Context Protocol (MCP) Client Dispatcher
            # -----------------------------------------------------------------
            elif tool_name == "mcp_connect":
                srv_name = args.get("server_name", "default")
                cmd = args.get("command", "")
                srv_args = args.get("args", [])
                client = StdioMCPClient(server_name=srv_name, command=cmd, args=srv_args)
                ok = await client.start()
                if ok:
                    self.mcp_clients[srv_name] = client
                    tools = list(client.discovered_tools.keys())
                    return ToolResult(tool_name=tool_name, success=True, output=f"Connected to MCP '{srv_name}'. Discovered tools: {tools}")
                return ToolResult(tool_name=tool_name, success=False, error=f"Failed to connect to MCP server '{srv_name}'.")

            elif tool_name == "mcp_call":
                srv_name = args.get("server_name", "")
                t_name = args.get("tool_name", "")
                t_args = args.get("arguments", {})
                client = self.mcp_clients.get(srv_name)
                if not client:
                    return ToolResult(tool_name=tool_name, success=False, error=f"MCP server '{srv_name}' not connected.")
                ok, res_text = await client.call_tool(t_name, t_args)
                return ToolResult(tool_name=tool_name, success=ok, output=res_text, error=None if ok else res_text)

"""

if "github_clone_or_fork" not in code:
    code = code.replace(dispatch_anchor, github_mcp_dispatch + dispatch_anchor)
    target.write_text(code, encoding="utf-8")
    print("[✓] Added GitHub Suite and MCP Client to ToolRegistry.")
