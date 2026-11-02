from pathlib import Path
import re

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

if "from dataclasses import" in code:
    code = re.sub(
        r'from dataclasses import ([^\n]+)',
        lambda m: m.group(0) if "asdict" in m.group(1) else f"from dataclasses import asdict, {m.group(1)}",
        code,
        count=1
    )
else:
    code = "from dataclasses import asdict\n" + code

target.write_text(code, encoding="utf-8")
print("[✓] Added asdict to dataclasses import in rooms_engine.py")
