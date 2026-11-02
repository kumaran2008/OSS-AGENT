from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Ensure 'import sys' is at the top of the file
if "import sys" not in code.split("class UnifiedAsyncEngine:")[0]:
    code = "import sys\n" + code

# 2. Defensively ensure 'import sys' is inside _retry_dispatcher
old_dispatcher = """            async def _retry_dispatcher(t_name, t_args):
                reg_mod = sys.modules.get("agent.pa_scaffolder.tool_registry")"""

new_dispatcher = """            async def _retry_dispatcher(t_name, t_args):
                import sys
                reg_mod = sys.modules.get("agent.pa_scaffolder.tool_registry")"""

if old_dispatcher in code:
    code = code.replace(old_dispatcher, new_dispatcher)

target.write_text(code, encoding="utf-8")
print("[✓] Added sys import to engine_harness.py and _retry_dispatcher.")
