from pathlib import Path
import re
import py_compile

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# Browser tool schemas to ensure present
browser_schemas_code = """
            {"type": "function", "function": {"name": "browser_navigate", "description": "Navigates headless browser (Playwright on desktop, CDP on mobile) to URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "browser_extract_text", "description": "Extracts innerText content from target DOM selector (default: 'body')", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "browser_eval_js", "description": "Evaluates JavaScript expression in active browser page", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}}},
            {"type": "function", "function": {"name": "browser_click_selector", "description": "Clicks target element matching CSS selector", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}}},
            {"type": "function", "function": {"name": "browser_screenshot", "description": "Captures screenshot of current page to file", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},
"""

# Check if browser_navigate schema is already inside
if '"name": "browser_navigate"' not in code:
    # Inject directly at the beginning of the list returned by get_all_tool_schemas
    target_pattern = r'(def get_all_tool_schemas\(self\)[^:]*:\s*(?:"""[^"]*""")?\s*return\s*\[)'
    if re.search(target_pattern, code):
        code = re.sub(target_pattern, r'\1' + browser_schemas_code, code, count=1)
        print("[✓] Injected browser schemas right after return [")
    else:
        # Fallback: match any return [ inside get_all_tool_schemas
        anchor = "return ["
        pos = code.find("def get_all_tool_schemas")
        if pos != -1:
            ret_pos = code.find(anchor, pos)
            if ret_pos != -1:
                insert_idx = ret_pos + len(anchor)
                code = code[:insert_idx] + browser_schemas_code + code[insert_idx:]
                print("[✓] Injected browser schemas via index position.")
            else:
                print("[!] Could not find 'return [' in get_all_tool_schemas")
        else:
            print("[!] Could not locate get_all_tool_schemas in tool_registry.py")

target.write_text(code, encoding="utf-8")
py_compile.compile(str(target), doraise=True)
print("[✓] tool_registry.py verified and compiled cleanly.")
