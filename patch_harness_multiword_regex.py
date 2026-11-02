from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_pattern = 'm = re.search(r"switch\\s+(?:the\\s+)?(\\w+)\\s+(?:model\\s+)?to\\s+([a-zA-Z0-9_\\-\\.]+)", clean)'
new_pattern = 'm = re.search(r"switch\\s+(?:the\\s+)?(\\w+)\\s+(?:model\\s+)?to\\s+(.+)$", clean)'

if old_pattern in code:
    code = code.replace(old_pattern, new_pattern)
    target.write_text(code, encoding="utf-8")
    print("[✓] Patched engine_harness.py with multi-word model name matcher.")
else:
    print("[i] Multi-word regex already present in engine_harness.py.")
