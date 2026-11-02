from pathlib import Path
import re

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add UnifiedBrowserController import
if "from agent.pa_scaffolder.unified_browser import UnifiedBrowserController" not in code:
    code = "from agent.pa_scaffolder.unified_browser import UnifiedBrowserController\n" + code

# 2. Add browser instance initialization in ToolRegistry.__init__
old_init_anchor = "self.remote_bridge = RemoteComputeBridge(self.workspace_root)"
new_init_anchor = old_init_anchor + "\n        self.browser = UnifiedBrowserController()"

if old_init_anchor in code and "self.browser =" not in code:
    code = code.replace(old_init_anchor, new_init_anchor)

# 3. Add dispatch handlers for browser tools
browser_dispatch_block = """            # -----------------------------------------------------------------
            # Adaptive Headless/Desktop Browser Tools (Playwright / CDP)
            # -----------------------------------------------------------------
            if tool_name == "browser_navigate":
                url = args.get("url", "https://example.com")
                res = await self.browser.navigate(url)
                ok = res.get("success", False)
                msg = f"Navigated to '{url}' via {res.get('backend', 'browser')}. Title: {res.get('title', 'N/A')}"
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=res.get("error"))

            elif tool_name == "browser_extract_text":
                selector = args.get("selector", "body")
                extracted = await self.browser.extract_text(selector)
                return ToolResult(tool_name=tool_name, success=True, output=str(extracted))

            elif tool_name == "browser_eval_js":
                script = args.get("script", "document.title")
                val = await self.browser.evaluate_js(script)
                return ToolResult(tool_name=tool_name, success=True, output=str(val))

            elif tool_name == "browser_click_selector":
                selector = args.get("selector", "")
                val = await self.browser.click_selector(selector)
                ok = "not found" not in str(val).lower() and "error" not in str(val).lower()
                return ToolResult(tool_name=tool_name, success=ok, output=str(val))

            elif tool_name == "browser_screenshot":
                path_arg = args.get("output_path", "workspace/screenshot.png")
                msg = await self.browser.capture_screenshot(path_arg)
                return ToolResult(tool_name=tool_name, success=True, output=msg)

"""

if "browser_navigate" not in code:
    anchor = '            if tool_name == "remote_cloud_sweep":'
    if anchor in code:
        code = code.replace(anchor, browser_dispatch_block + anchor)

# 4. Add schemas to get_all_tool_schemas
schemas_to_add = """            {"type": "function", "function": {"name": "browser_navigate", "description": "Navigates headless browser (Playwright on desktop, CDP on mobile) to URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "browser_extract_text", "description": "Extracts innerText content from target DOM selector (default: 'body')", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "browser_eval_js", "description": "Evaluates JavaScript expression in active browser page", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}}},
            {"type": "function", "function": {"name": "browser_click_selector", "description": "Clicks target element matching CSS selector", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}}},
            {"type": "function", "function": {"name": "browser_screenshot", "description": "Captures screenshot of current page to file", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},
"""

if "browser_navigate" not in code or '"name": "browser_navigate"' not in code:
    schema_anchor = '{"type": "function", "function": {"name": "remote_cloud_sweep",'
    if schema_anchor in code:
        code = code.replace(schema_anchor, schemas_to_add + schema_anchor)

target.write_text(code, encoding="utf-8")

import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] agent/pa_scaffolder/tool_registry.py compiled cleanly with browser tools.")
