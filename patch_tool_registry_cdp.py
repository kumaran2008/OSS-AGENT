from pathlib import Path
import re

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Ensure DesktopCDPEngine import
if "from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine" not in code:
    code = "from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine\n" + code

# 2. Add cdp_engine initialization in ToolRegistry.__init__
old_init_anchor = "self.remote_bridge = RemoteComputeBridge(self.workspace_root)"
new_init_anchor = old_init_anchor + "\n        self.cdp_engine = DesktopCDPEngine()"

if old_init_anchor in code and "self.cdp_engine =" not in code:
    code = code.replace(old_init_anchor, new_init_anchor)

# 3. Add dispatch handlers for browser tools
cdp_dispatch_block = """            # -----------------------------------------------------------------
            # Native Chrome DevTools Protocol (CDP) Browser Tools
            # -----------------------------------------------------------------
            if tool_name == "browser_navigate":
                url = args.get("url", "https://example.com")
                res = await self.cdp_engine.navigate(url)
                ok = res.get("success", False) if isinstance(res, dict) else True
                msg = f"Navigated to '{url}'. Status: {res}"
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else str(res))

            elif tool_name == "browser_extract_text":
                selector = args.get("selector", "body")
                script = f"(function() { let el = document.querySelector('{selector}'); return el ? (el.innerText || el.textContent) : 'Element not found'; })()"
                res = await self.cdp_engine.evaluate_js(script)
                val = res.get("value", "") if isinstance(res, dict) else str(res)
                return ToolResult(tool_name=tool_name, success=True, output=str(val))

            elif tool_name == "browser_eval_js":
                script = args.get("script", "document.title")
                res = await self.cdp_engine.evaluate_js(script)
                val = res.get("value", "") if isinstance(res, dict) else str(res)
                return ToolResult(tool_name=tool_name, success=True, output=str(val))

            elif tool_name == "browser_click_selector":
                selector = args.get("selector", "")
                script = f"(function() { let el = document.querySelector('{selector}'); if (el) { el.click(); return 'Clicked ' + selector; } return 'Selector not found'; })()"
                res = await self.cdp_engine.evaluate_js(script)
                val = res.get("value", "") if isinstance(res, dict) else str(res)
                ok = "not found" not in str(val).lower()
                return ToolResult(tool_name=tool_name, success=ok, output=str(val))

"""

if "browser_navigate" not in code:
    anchor = '            if tool_name == "remote_cloud_sweep":'
    if anchor in code:
        code = code.replace(anchor, cdp_dispatch_block + anchor)

# 4. Add function schemas to get_all_tool_schemas
schemas_to_add = """            {"type": "function", "function": {"name": "browser_navigate", "description": "Navigates headless/desktop browser to a target URL via Chrome DevTools Protocol", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "browser_extract_text", "description": "Extracts innerText content from target DOM selector (default: 'body')", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "browser_eval_js", "description": "Evaluates JavaScript in active page context via CDP", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}}},
            {"type": "function", "function": {"name": "browser_click_selector", "description": "Clicks target element matching CSS selector", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}}},
"""

if "browser_navigate" not in code or '"name": "browser_navigate"' not in code:
    schema_anchor = '{"type": "function", "function": {"name": "remote_cloud_sweep",'
    if schema_anchor in code:
        code = code.replace(schema_anchor, schemas_to_add + schema_anchor)

target.write_text(code, encoding="utf-8")

import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] Registered CDP browser tools in ToolRegistry.")
