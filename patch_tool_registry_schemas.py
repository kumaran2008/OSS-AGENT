from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

schema_method = """    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        \"\"\"Wire 4: Returns OpenAI-compatible tool schemas including registered dynamic MCP servers.\"\"\"
        schemas = [
            {"type": "function", "function": {"name": "bash_execute", "description": "Runs terminal commands in PTY", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
            {"type": "function", "function": {"name": "file_read", "description": "Reads file lines", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "start_line": {"type": "integer"}, "line_count": {"type": "integer"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "file_patch", "description": "Applies unified diff patch to a file", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "diff": {"type": "string"}}, "required": ["file_path", "diff"]}}},
            {"type": "function", "function": {"name": "repo_get_map", "description": "Returns PageRank-ranked repository symbol map", "parameters": {"type": "object", "properties": {"max_tokens": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "github_list_issues", "description": "Lists open GitHub issues", "parameters": {"type": "object", "properties": {"repo": {"type": "string"}, "limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "github_create_pr", "description": "Creates a GitHub Pull Request", "parameters": {"type": "object", "properties": {"repo_name": {"type": "string"}, "branch": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}}, "required": ["repo_name", "branch", "title", "body"]}}},
            {"type": "function", "function": {"name": "mcp_call", "description": "Dispatches an on-demand MCP tool invocation", "parameters": {"type": "object", "properties": {"server_id": {"type": "string"}, "tool_name": {"type": "string"}, "arguments": {"type": "object"}, "user_prompt": {"type": "string"}}, "required": ["tool_name"]}}}
        ]
        return schemas
"""

if "def get_all_tool_schemas" not in code:
    anchor = "    async def dispatch(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:"
    code = code.replace(anchor, schema_method + "\n" + anchor)
    target.write_text(code, encoding="utf-8")
    print("[✓] Added get_all_tool_schemas to ToolRegistry.")
