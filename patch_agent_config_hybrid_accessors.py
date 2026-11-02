from pathlib import Path
import re
import py_compile

target = Path("agent/pa_scaffolder/agent_config.py")
code = target.read_text(encoding="utf-8")

# Define CallableStr if not already present
callable_str_def = """class CallableStr(str):
    def __call__(self):
        return self

class CallableList(list):
    def __call__(self):
        return self
"""

# Replace existing class definitions if present, or prepend
code = re.sub(r'class CallableList[^\n]*:.*?(?=\nclass |\Z)', '', code, flags=re.DOTALL)
code = re.sub(r'class CallableStr[^\n]*:.*?(?=\nclass |\Z)', '', code, flags=re.DOTALL)
code = callable_str_def + "\n" + code

# Clean up agent_name definition and replace with hybrid property
agent_name_pattern = r'def agent_name\(self\)[^:]*:.*?(?=\n    def |\n    @|\Z)'
new_agent_name = """@property
    def agent_name(self) -> str:
        val = self.data.get("agent_name", "Hype")
        return CallableStr(val)"""

code = re.sub(agent_name_pattern, new_agent_name, code, flags=re.DOTALL)

# Ensure acknowledgments property returns CallableList
ack_pattern = r'def acknowledgments\(self\)[^:]*:.*?(?=\n    def |\n    @|\Z)'
new_ack = """@property
    def acknowledgments(self) -> list:
        default_acks = ["Yes?", "I'm listening.", "Go ahead.", "Online.", "Ready."]
        val = self.data.get("acknowledgments", default_acks)
        return CallableList(val)"""

if "def acknowledgments" in code:
    code = re.sub(ack_pattern, new_ack, code, flags=re.DOTALL)
else:
    # Insert right before @property def agent_name
    code = code.replace("@property\n    def agent_name", new_ack + "\n\n    @property\n    def agent_name", 1)

target.write_text(code, encoding="utf-8")
py_compile.compile(str(target), doraise=True)
print("[✓] agent_config.py patched with dual attribute/callable accessors.")
