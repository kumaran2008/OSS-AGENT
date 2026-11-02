from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# Replace sync calls with await execute_free_desktop_query_async
old_cdp_call = "_, spoken_text = self.cdp_engine.execute_free_desktop_query(clean_text)"
new_cdp_call = "_, spoken_text = await self.cdp_engine.execute_free_desktop_query_async(clean_text)"

if old_cdp_call in code:
    code = code.replace(old_cdp_call, new_cdp_call)
    target.write_text(code, encoding="utf-8")
    print("[✓] engine_harness.py patched to await execute_free_desktop_query_async")
else:
    print("[i] CDP calls in engine_harness.py already async or using updated signatures.")
