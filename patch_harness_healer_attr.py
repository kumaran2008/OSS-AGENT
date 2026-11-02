from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Ensure IsolatedSelfHealer import is present
if "from agent.pa_scaffolder.isolated_self_healer import IsolatedSelfHealer" not in code:
    code = "from agent.pa_scaffolder.isolated_self_healer import IsolatedSelfHealer\n" + code

# 2. Add self.isolated_healer to UnifiedAsyncEngine.__init__
if "self.isolated_healer =" not in code:
    init_match = re.search(r'(class UnifiedAsyncEngine:[^\n]*\n(?:[ \t]+[^\n]*\n)*?[ \t]+def __init__\([^)]*\):[^\n]*\n(?:[ \t]+[^\n]*\n)*?)([ \t]+)(self\.tools\s*=\s*[^\n]+)', code)
    if init_match:
        indent = init_match.group(2)
        code = code[:init_match.end()] + f"\n{indent}self.isolated_healer = IsolatedSelfHealer(self.tools.workspace_root)" + code[init_match.end():]
    else:
        # Fallback anchor: right after self.tools initialization
        code = re.sub(
            r'(self\.tools\s*=\s*[^\n]+)',
            r'\1\n        self.isolated_healer = IsolatedSelfHealer(self.tools.workspace_root)',
            code,
            count=1
        )

# 3. Defensive guard inside dispatch_tool_with_self_healing
old_guard = "self.isolated_healer.workspace_root = self.tools.workspace_root"
new_guard = """if not hasattr(self, "isolated_healer") or self.isolated_healer is None:
            self.isolated_healer = IsolatedSelfHealer(self.tools.workspace_root)
        self.isolated_healer.workspace_root = self.tools.workspace_root"""

if old_guard in code and "if not hasattr(self, \"isolated_healer\")" not in code:
    code = code.replace(old_guard, new_guard)

target.write_text(code, encoding="utf-8")

# Validate compile
import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] Patched UnifiedAsyncEngine with isolated_healer initialization.")
