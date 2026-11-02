import ast
from pathlib import Path
import py_compile

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")
tree = ast.parse(code)
lines = code.splitlines()

# Browser schemas to inject
browser_schemas_raw = [
    '            {"type": "function", "function": {"name": "browser_navigate", "description": "Navigates headless browser (Playwright on desktop, CDP on mobile) to URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},',
    '            {"type": "function", "function": {"name": "browser_extract_text", "description": "Extracts innerText content from target DOM selector (default: \'body\')", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},',
    '            {"type": "function", "function": {"name": "browser_eval_js", "description": "Evaluates JavaScript expression in active browser page", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}}},',
    '            {"type": "function", "function": {"name": "browser_click_selector", "description": "Clicks target element matching CSS selector", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}}},',
    '            {"type": "function", "function": {"name": "browser_screenshot", "description": "Captures screenshot of current page to file", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},'
]

# Find get_all_tool_schemas
target_fn = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "get_all_tool_schemas":
        target_fn = node
        break

if not target_fn:
    print("[!] Could not locate get_all_tool_schemas function.")
    exit(1)

# Find the Return node inside get_all_tool_schemas
return_node = None
for child in ast.walk(target_fn):
    if isinstance(child, ast.Return) and isinstance(child.value, ast.List):
        return_node = child
        break

if return_node and isinstance(return_node.value, ast.List):
    # Insert right inside the opening bracket of return [...]
    start_line = return_node.lineno - 1
    # Check if 'return [' is on start_line
    for i in range(start_line, return_node.end_lineno):
        if "[" in lines[i]:
            bracket_idx = i
            # Insert immediately after the line with the opening bracket
            lines = lines[:bracket_idx + 1] + browser_schemas_raw + lines[bracket_idx + 1:]
            print(f"[✓] Successfully injected browser schemas at line {bracket_idx + 1}.")
            break
else:
    # Alternative: rewrite get_all_tool_schemas method directly
    fn_start = target_fn.lineno - 1
    fn_end = target_fn.end_lineno
    new_fn = [
        "    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:",
        '        """Returns JSON function schemas for LLM tool binding."""',
        "        schemas = ["
    ] + browser_schemas_raw + [
        "        ]",
        "        # Include existing schemas if defined",
        "        try:",
        "            base_schemas = self._get_base_schemas()",
        "            return schemas + base_schemas",
        "        except Exception:",
        "            return schemas"
    ]
    lines = lines[:fn_start] + new_fn + lines[fn_end:]
    print("[✓] Replaced get_all_tool_schemas via full block injection.")

new_code = "\n".join(lines)
target.write_text(new_code, encoding="utf-8")
py_compile.compile(str(target), doraise=True)
print("[✓] agent/pa_scaffolder/tool_registry.py compiled cleanly with browser tool schemas.")
