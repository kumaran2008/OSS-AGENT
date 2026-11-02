import os
import subprocess
from pathlib import Path
from agent.pa_scaffolder import (
    PersonalAgentConfig,
    AgentPersona,
    OperatorProfile,
    InferenceConfig,
    PersonalAgentScaffolder
)

demo_home = Path("./test_pa_demo").resolve()
print(f"=== 1. DEPLOYING FULL SYSTEM TO: {demo_home} ===")

config = PersonalAgentConfig(
    persona=AgentPersona(
        name="Hype",
        wake_word="hype",
        tone_style="Supportive & High Energy"
    ),
    operator=OperatorProfile(
        call_sign="Chief",
        wake_time="06:30",
        gym_time="19:00 - 20:00",
        daily_calories_target=2350
    ),
    inference=InferenceConfig(
        engine="app_automation",
        app_mode=True,
        app_target="chatgpt"
    ),
    pa_home=str(demo_home)
)

scaffolder = PersonalAgentScaffolder(target_home=str(demo_home))
deployed_dir = scaffolder.deploy(config)
assert deployed_dir.exists()
print(f"[✓] Deployment artifacts generated.")

# Write the launcher
launcher = deployed_dir / "pa"
with open(launcher, "w") as f:
    f.write(f'#!/usr/bin/env bash\npython3 "{deployed_dir}/runtime/pa_runtime.py" "$@"\n')
os.chmod(launcher, 0o755)

print("\n=== 2. EXECUTING LIVE PA RUNTIME VIA LAUNCHER ===")
res = subprocess.run([str(launcher)], capture_output=True, text=True)
print(f"Stdout:\n{res.stdout.strip()}")
assert res.returncode == 0
assert "Hey Chief! Hype is online" in res.stdout

print("\n=== 3. VERIFYING COGNITIVE BRAIN PERSISTENCE ===")
import sqlite3
conn = sqlite3.connect(deployed_dir / "memory" / "brain.db")
cur = conn.cursor()
cur.execute("SELECT metric_key, metric_value FROM habits_and_routines WHERE metric_key='daily_calories_target'")
row = cur.fetchone()
conn.close()
print(f"[✓] Operator Target Calories logged in brain: {row[1]}")
assert row[1] == "2350"

print("\n============================================================")
print(">>> ALL 4 PHASES + END-TO-END WORKFLOW VERIFIED SUCCESSFULLY <<<")
print("============================================================")
