from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add ClaudeEngine import
if "from agent.pa_scaffolder.claude_engine import ClaudeEngine" not in code:
    code = "from agent.pa_scaffolder.claude_engine import ClaudeEngine\n" + code

# 2. Initialize ClaudeEngine in __init__
old_init = "self.tools = ToolRegistry()"
new_init = "self.tools = ToolRegistry()\n        self.claude = ClaudeEngine()"

if old_init in code and "self.claude = ClaudeEngine()" not in code:
    code = code.replace(old_init, new_init)

# 3. Replace the mock Claude vision response with live call + CDP fallback
old_vision_block = """            else:
                # Route via Claude / Frontier reasoning
                full_resp = (
                    "<clipboard_code>\\n"
                    "def solve_boundary():\\n"
                    "    return items[0] if items else None\\n"
                    "</clipboard_code>\\n"
                    "<spoken_reason>\\n"
                    "You had an out-of-bounds IndexError on line 42. I've placed the corrected guard on your clipboard.\\n"
                    "</spoken_reason>"
                )
                backend_label = "CLAUDE_VISION_API" """

new_vision_block = """            else:
                # Live Claude Vision API Call
                if self.claude.is_configured():
                    ok, resp_text = self.claude.analyze_screen_error(triage_prompt, image_path=str(img_path) if img_path else None)
                    if ok:
                        full_resp = resp_text
                        backend_label = "CLAUDE_VISION_API"
                    else:
                        # Fallback to Desktop CDP on API error
                        async for tok in self.cdp_bridge.stream_browser_generation(prompt=triage_prompt, image_path=str(img_path) if img_path else None):
                            full_resp += tok
                        backend_label = "DESKTOP_CDP_VISION"
                else:
                    # No API key set -> Auto-fallback to free Desktop CDP session
                    async for tok in self.cdp_bridge.stream_browser_generation(prompt=triage_prompt, image_path=str(img_path) if img_path else None):
                        full_resp += tok
                    backend_label = "DESKTOP_CDP_VISION" """

if old_vision_block.strip() in code:
    code = code.replace(old_vision_block.strip(), new_vision_block.strip())
    print("[✓] Replaced Claude vision mock with live API caller & CDP auto-fallback.")
else:
    # Fallback replacement if whitespace differs
    print("[i] Patching Claude handler dynamically...")
    import re
    code = re.sub(
        r'else:\s+# Route via Claude.*?"CLAUDE_VISION_API"',
        new_vision_block.strip(),
        code,
        flags=re.DOTALL
    )

target.write_text(code, encoding="utf-8")
print("[✓] Successfully wired ClaudeEngine into engine_harness.py")
