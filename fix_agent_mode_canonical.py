from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Remove any duplicate 'class AgentMode' definition blocks in engine_harness.py
lines = code.splitlines(keepends=True)
new_lines = []
skip = False
removed_old_class = False

for line in lines:
    if re.match(r'^[ \t]*class AgentMode\b', line):
        skip = True
        removed_old_class = True
        continue
    if skip:
        # Keep skipping indented lines, empty lines, and comments inside the class body
        if line.startswith(" ") or line.startswith("\t") or line.strip() == "" or line.strip().startswith("#"):
            continue
        else:
            skip = False
    new_lines.append(line)

code = "".join(new_lines)

# 2. Clean out any conflicting imports of AgentMode from older files
code = re.sub(
    r'from agent\.pa_scaffolder\.(?!rooms_engine)[a-zA-Z0-9_]+ import ([^\n]*\bAgentMode\b[^\n]*)',
    lambda m: m.group(0).replace("AgentMode,", "").replace(", AgentMode", "").replace("AgentMode", ""),
    code
)

# 3. Ensure rooms_engine import at the top imports AgentMode
if "from agent.pa_scaffolder.rooms_engine import" in code:
    code = re.sub(
        r'from agent\.pa_scaffolder\.rooms_engine import ([^\n]+)',
        lambda m: m.group(0) if "AgentMode" in m.group(1) else f"from agent.pa_scaffolder.rooms_engine import AgentMode, {m.group(1)}",
        code,
        count=1
    )
else:
    code = "from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode, SystemTelemetryCache\n" + code

target.write_text(code, encoding="utf-8")
print(f"[✓] Unified AgentMode in engine_harness.py (Removed duplicate class: {removed_old_class})")

# 4. If legacy modes.py exists, align it as well
legacy_modes = Path("agent/pa_scaffolder/modes.py")
if legacy_modes.exists():
    legacy_modes.write_text(
        "from agent.pa_scaffolder.rooms_engine import AgentMode, ModeProfile, MODE_REGISTRY\n",
        encoding="utf-8"
    )
    print("[✓] Re-exported canonical AgentMode from modes.py.")
