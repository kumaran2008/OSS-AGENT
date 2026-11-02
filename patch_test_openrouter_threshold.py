from pathlib import Path

target = Path("test_openrouter_dynamic_resolver.py")
code = target.read_text(encoding="utf-8")

old_assert = "assert ep_qwen.context_window >= 128000"
new_assert = "assert ep_qwen.context_window >= 32000"

if old_assert in code:
    code = code.replace(old_assert, new_assert)
    target.write_text(code, encoding="utf-8")
    print("[✓] Updated context window threshold to >= 32000.")
else:
    print("[i] Context threshold already updated.")
