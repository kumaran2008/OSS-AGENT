from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Ensure Callable is imported from typing
if "from typing import" in code:
    code = re.sub(r'from typing import ([^\n]+)', lambda m: f"from typing import Callable, {m.group(1)}" if "Callable" not in m.group(1) else m.group(0), code, count=1)
else:
    code = "from typing import Callable, Optional, Dict, Any, List, Tuple\n" + code

# 2. Ensure re is imported
if "import re" not in code.split("class UnifiedAsyncEngine:")[0]:
    code = "import re\n" + code

target.write_text(code, encoding="utf-8")
print("[✓] Added Callable and re imports to engine_harness.py")
