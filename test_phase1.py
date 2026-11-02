import sys
import json
import sqlite3
from pathlib import Path

from agent.pa_scaffolder import (
    PersonalAgentConfig,
    AgentPersona,
    OperatorProfile,
    InferenceConfig,
    PersonalAgentScaffolder
)

# 1. Define custom user-chosen profile
custom_config = PersonalAgentConfig(
    persona=AgentPersona(
        name="Nova",
        wake_word="nova",
        tone_style="Laser-focused Builder",
        voice_profile="neutral-crisp-1"
    ),
    operator=OperatorProfile(
        call_sign="Alex",
        work_hours="10:00 - 19:00",
        daily_calories_target=2400,
        daily_protein_target_g=160
    ),
    inference=InferenceConfig(
        engine="direct_api",
        model="deepseek-chat",
        api_key="sk-test-mock-key"
    )
)

# 2. Scaffold into sandbox test directory
sandbox_path = Path("./test_pa_env").resolve()
scaffolder = PersonalAgentScaffolder(target_home=str(sandbox_path))
deployed_home = scaffolder.deploy(custom_config)

print(f"[✓] Phase 1: PA deployed to {deployed_home}")

# 3. Verify SQLite Brain Database
db_file = sandbox_path / "memory" / "brain.db"
assert db_file.exists(), "brain.db was not created!"
conn = sqlite3.connect(db_file)
cur = conn.cursor()
cur.execute("SELECT metric_key, metric_value FROM habits_and_routines")
rows = dict(cur.fetchall())
conn.close()
print(f"[✓] Brain DB verified. Habits logged: {rows}")
assert rows["daily_calories_target"] == "2400"
assert rows["work_hours"] == "10:00 - 19:00"

# 4. Verify and execute Standalone Runtime
sys.path.insert(0, str(sandbox_path / "runtime"))
from pa_runtime import StandalonePersonalAgent

agent = StandalonePersonalAgent(pa_home=str(sandbox_path))
print(f"[✓] Greeting test: \"{agent.greeting()}\"")
assert agent.name == "Nova"
assert agent.operator == "Alex"

# 5. In-flight identity update test (Renaming to 'AegisOne' and changing tone on the fly)
print("\n[+] Testing live in-flight persona update tool...")
update_result = agent.update_agent_persona(
    new_name="AegisOne",
    new_tone="Hyper-efficient Minimalist",
    new_call_sign="Chief"
)
print(f"[✓] Tool return: {update_result}")

# Re-inspect to prove persistence
agent_reloaded = StandalonePersonalAgent(pa_home=str(sandbox_path))
assert agent_reloaded.name == "AegisOne"
assert agent_reloaded.operator == "Chief"
print(f"[✓] Post-update greeting: \"{agent_reloaded.greeting()}\"")
print("\n>>> PHASE 1 COMPLETE: Scaffolding, SQLite Brain & In-Flight Identity validated with 0 errors.")
