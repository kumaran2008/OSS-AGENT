from pathlib import Path
import re

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Clean out any previous broken browser snippets or syntax-broken f-strings
code = re.sub(
    r'[ \t]*# -+\n[ \t]*# (?:Native Chrome DevTools Protocol|Adaptive Headless/Desktop Browser).*?(?=\n[ \t]*if tool_name == "remote_cloud_sweep":|\n[ \t]*elif tool_name == "remote_cloud_sweep":)',
    '',
    code,
    flags=re.DOTALL
)

# Remove any broken inline script f-string if leftover
code = re.sub(r'.*let el = document\.querySelector.*?\n', '', code)

# 2. Ensure UnifiedBrowserController import is present
if "from agent.pa_scaffolder.unified_browser import UnifiedBrowserController" not in code:
    code = "from agent.pa_scaffolder.unified_browser import UnifiedBrowserController\n" + code

# 3. Ensure self.browser initialization in __init__
if "self.browser = UnifiedBrowserController()" not in code:
    if "self.remote_bridge = RemoteComputeBridge(self.workspace_root)" in code:
        code = code.replace(
            "self.remote_bridge = RemoteComputeBridge(self.workspace_root)",
            "self.remote_bridge = RemoteComputeBridge(self.workspace_root)\n        self.browser = UnifiedBrowserController()"
        )

# 4. Insert the clean dispatch block right before remote_cloud_sweep
browser_dispatch = """            # -----------------------------------------------------------------
            # Adaptive Headless/Desktop Browser Tools (Playwright / CDP)
            # -----------------------------------------------------------------
            if tool_name == "browser_navigate":
                url = args.get("url", "https://example.com")
                res = await self.browser.navigate(url)
                ok = res.get("success", False)
                backend = res.get("backend", "browser")
                title = res.get("title", "N/A")
                msg = f"Navigated to '{url}' via {backend}. Title: {title}"
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

            elif tool_name == "remote_cloud_sweep":"""

if "if tool_name == \"browser_navigate\":" not in code:
    if 'if tool_name == "remote_cloud_sweep":' in code:
        code = code.replace('if tool_name == "remote_cloud_sweep":', browser_dispatch, 1)
    elif 'elif tool_name == "remote_cloud_sweep":' in code:
        code = code.replace('elif tool_name == "remote_cloud_sweep":', browser_dispatch, 1)

# 5. Clean out duplicate/broken browser schema declarations if present
code = re.sub(r'\{"type":\s*"function",\s*"function":\s*\{"name":\s*"browser_[^}]+\}\}\},?\n?', '', code)

# 6. Add schemas cleanly right before remote_cloud_sweep schema
schemas_to_insert = """            {"type": "function", "function": {"name": "browser_navigate", "description": "Navigates headless browser (Playwright on desktop, CDP on mobile) to URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "browser_extract_text", "description": "Extracts innerText content from target DOM selector (default: 'body')", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "browser_eval_js", "description": "Evaluates JavaScript expression in active browser page", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}}},
            {"type": "function", "function": {"name": "browser_click_selector", "description": "Clicks target element matching CSS selector", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}}},
            {"type": "function", "function": {"name": "browser_screenshot", "description": "Captures screenshot of current page to file", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "remote_cloud_sweep","""

if '{"type": "function", "function": {"name": "remote_cloud_sweep",' in code:
    code = code.replace('{"type": "function", "function": {"name": "remote_cloud_sweep",', schemas_to_insert, 1)

target.write_text(code, encoding="utf-8")

# 7. Pre-flight bytecode compilation check
import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] agent/pa_scaffolder/tool_registry.py repaired and successfully compiled!")
