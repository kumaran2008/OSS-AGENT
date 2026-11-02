from pathlib import Path
import re
import py_compile

target = Path("agent/pa_scaffolder/agent_config.py")
code = target.read_text(encoding="utf-8")

# Class that behaves BOTH as a list and as a callable returning itself
callable_list_def = """class CallableList(list):
    def __call__(self):
        return self
"""

if "class CallableList" not in code:
    code = callable_list_def + "\n" + code

# Clean up any prior @property def acknowledgments
code = re.sub(r'[ \t]*@property\s*\n[ \t]*def acknowledgments\([^\)]*\):[^\n]*\n(?:[ \t]+[^\n]*\n)*', '', code)

# Clean up any def acknowledgments
code = re.sub(r'[ \t]*def acknowledgments\([^\)]*\):[^\n]*\n(?:[ \t]+[^\n]*\n)*', '', code)

ack_method = """    def acknowledgments(self) -> list:
        \"\"\"Returns acknowledgment phrases. Safe as both method and attribute.\"\"\"
        default_acks = ["Yes?", "I'm listening.", "Go ahead.", "Online.", "Ready."]
        raw = self.data.get("acknowledgments", default_acks)
        return CallableList(raw)
"""

anchor = "    def agent_name(self)"
if anchor in code:
    code = code.replace(anchor, ack_method + "\n" + anchor, 1)

target.write_text(code, encoding="utf-8")
py_compile.compile(str(target), doraise=True)
print("[✓] CallableList acknowledgments installed cleanly.")
