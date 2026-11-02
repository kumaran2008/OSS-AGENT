from pathlib import Path
import ast
import py_compile

target = Path("agent/pa_scaffolder/agent_config.py")
code = target.read_text(encoding="utf-8")

default_acks = '["Yes?", "I\'m listening.", "Go ahead.", "Online."]'

if "acknowledgments" not in code:
    # Check if dataclass or normal class
    if "@dataclass" in code:
        # Insert field with default
        anchor = "agent_name: str"
        replacement = f"agent_name: str\n    acknowledgments: list = field(default_factory=lambda: {default_acks})"
        if "from dataclasses import" in code and "field" not in code:
            code = code.replace("from dataclasses import ", "from dataclasses import field, ")
        if anchor in code:
            code = code.replace(anchor, replacement, 1)
    else:
        # In __init__
        anchor = "self.agent_name = "
        replacement = f"self.acknowledgments = {default_acks}\n        self.agent_name = "
        if anchor in code:
            code = code.replace(anchor, replacement, 1)

    target.write_text(code, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)
    print("[✓] Added acknowledgments attribute to AgentConfig.")
else:
    print("[i] acknowledgments already present.")
