from pathlib import Path
import py_compile

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

anchor = '        schemas = ['
browser_schemas = """        schemas = [
            {"type": "function", "function": {"name": "browser_navigate", "description": "Navigates headless browser (Playwright on desktop, CDP on mobile) to URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "browser_extract_text", "description": "Extracts innerText content from target DOM selector (default: 'body')", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "browser_eval_js", "description": "Evaluates JavaScript expression in active browser page", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}}},
            {"type": "function", "function": {"name": "browser_click_selector", "description": "Clicks target element matching CSS selector", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}}},
            {"type": "function", "function": {"name": "browser_screenshot", "description": "Captures screenshot of current page to file", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},"""

if anchor in code:
    code = code.replace(anchor, browser_schemas, 1)
    target.write_text(code, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)
    print("[✓] Successfully injected browser schemas into get_all_tool_schemas.")
else:
    print("[!] Anchor 'schemas = [' not found in tool_registry.py.")
