from pathlib import Path
import re

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

if "def sandbox(self)" not in code:
    property_code = """    @property
    def sandbox(self):
        return self.pty
"""
    code = re.sub(r'(class ToolRegistry[^\n]*:\n)', r'\1' + property_code + '\n', code, count=1)
    target.write_text(code, encoding="utf-8")
    print("[✓] Added @property def sandbox to ToolRegistry.")
else:
    print("[i] sandbox property already present in ToolRegistry.")
