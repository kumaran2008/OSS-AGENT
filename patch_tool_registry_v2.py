from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add repo_get_map dispatch case
old_dispatch = '        elif tool_name == "repo_find_symbol":'
new_dispatch = """        elif tool_name == "repo_get_map":
            tokens = int(args.get("max_tokens", 1000))
            if not self.symbol_mapper.file_indices:
                self.symbol_mapper.index_repository()
            repo_map = self.symbol_mapper.get_repo_map_summary(max_tokens=tokens)
            return ToolResult(tool_name=tool_name, success=True, output=repo_map)

        elif tool_name == "repo_find_symbol":"""

if old_dispatch in code and "repo_get_map" not in code:
    code = code.replace(old_dispatch, new_dispatch)

# 2. Add repo_get_map tool schema
old_schema_anchor = '                    "name": "repo_find_symbol",'
new_schema = """                    "name": "repo_get_map",
                    "description": "Generates a PageRank-prioritized structural map of the repository with elided bodies.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "max_tokens": {"type": "integer", "description": "Token budget (default: 1000)"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
""" + old_schema_anchor

if old_schema_anchor in code and "repo_get_map" not in code:
    code = code.replace(old_schema_anchor, new_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered repo_get_map in ToolRegistry.")
