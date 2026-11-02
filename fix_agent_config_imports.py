from pathlib import Path
import py_compile

target = Path("agent/pa_scaffolder/agent_config.py")
code = target.read_text(encoding="utf-8")

# Ensure standard imports are present at the absolute top of the file
header_imports = """import os
import re
import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

class CallableStr(str):
    def __call__(self):
        return self

class CallableList(list):
    def __call__(self):
        return self
"""

# Remove existing duplicate class definitions to prevent clutter
import re
code = re.sub(r'class CallableList[^\n]*:.*?(?=\nclass |\Z)', '', code, flags=re.DOTALL)
code = re.sub(r'class CallableStr[^\n]*:.*?(?=\nclass |\Z)', '', code, flags=re.DOTALL)

# Clean out any old/loose duplicate import lines at the top
code = re.sub(r'^(?:import [^\n]+\n|from [^\n]+ import [^\n]+\n)+', '', code)

# Combine header with the body
new_code = header_imports + "\n" + code.strip() + "\n"

target.write_text(new_code, encoding="utf-8")
py_compile.compile(str(target), doraise=True)
print("[✓] Top-level imports and helper classes restored cleanly in agent_config.py")
