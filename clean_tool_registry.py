from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# Remove any residual injected bug lines from previous failed runs
injected_snippet = "if int(args.get('line_count', 0)) > 20:\n                    raise IndexError('PA Internal Buffer Limit Exceeded in file_read')\n"
if injected_snippet in code:
    code = code.replace(injected_snippet, "")
    target.write_text(code, encoding="utf-8")
    print("[✓] Cleaned residual bug from tool_registry.py.")
else:
    print("[i] tool_registry.py is already clean.")
