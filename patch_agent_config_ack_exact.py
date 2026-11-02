from pathlib import Path
import py_compile

target = Path("agent/pa_scaffolder/agent_config.py")
code = target.read_text(encoding="utf-8")

ack_property = """    @property
    def acknowledgments(self) -> list:
        \"\"\"List of conversational acknowledgment phrases when wake word is detected.\"\"\"
        default_acks = ["Yes?", "I'm listening.", "Go ahead.", "Online.", "Ready."]
        return self.data.get("acknowledgments", default_acks)
"""

if "def acknowledgments(" not in code:
    anchor = "    def agent_name(self)"
    if anchor in code:
        code = code.replace(anchor, ack_property + "\n" + anchor, 1)
        target.write_text(code, encoding="utf-8")
        py_compile.compile(str(target), doraise=True)
        print("[✓] Added acknowledgments property to AgentConfig.")
    else:
        print("[!] Anchor 'def agent_name(self)' not found.")
else:
    print("[i] acknowledgments already present.")
