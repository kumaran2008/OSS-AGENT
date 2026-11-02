from pathlib import Path
import re

target = Path("agent/pa_scaffolder/experiment_runner.py")
code = target.read_text(encoding="utf-8")

# Ensure Union is present in typing import
if "from typing import" in code:
    code = re.sub(r'from typing import ([^\n]+)', r'from typing import \1, Union', code, count=1)
    # Deduplicate in case Union was repeated
    code = re.sub(r'\bUnion,\s*Union\b', 'Union', code)
else:
    code = "from typing import Dict, Any, List, Optional, Tuple, Union\n" + code

# Ensure Path is imported
if "from pathlib import" not in code and "import pathlib" not in code:
    code = "from pathlib import Path\n" + code

target.write_text(code, encoding="utf-8")

import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] Corrected imports in experiment_runner.py.")
