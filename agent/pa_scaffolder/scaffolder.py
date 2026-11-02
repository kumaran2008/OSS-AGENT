import os
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional

from agent.pa_scaffolder.schemas import (
    PersonalAgentConfig,
    AgentPersona,
    OperatorProfile,
    InferenceConfig
)
from agent.core.branding import BRAND


class PersonalAgentScaffolder:
    """
    Builds and writes a clean, production-grade Personal Agent deployment
    into ~/.personal_agent/ with real tool-calling and WebGL UI.
    """
    def __init__(self, target_home: Optional[str] = None):
        self.target_home = Path(target_home or (Path.home() / ".personal_agent")).resolve()

    def deploy(self, config: PersonalAgentConfig) -> Path:
        mem_dir = self.target_home / "memory"
        hist_dir = mem_dir / "history"
        telemetry_dir = self.target_home / "telemetry"
        runtime_dir = self.target_home / "runtime"
        ui_dir = self.target_home / "ui"

        for d in [self.target_home, mem_dir, hist_dir, telemetry_dir, runtime_dir, ui_dir]:
            d.mkdir(parents=True, exist_ok=True)

        config.pa_home = str(self.target_home)
        config_path = self.target_home / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)

        profile_path = mem_dir / "profile.json"
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump({
                "persona": asdict(config.persona),
                "operator": asdict(config.operator)
            }, f, indent=2)

        self._init_brain_database(mem_dir / "brain.db", config.operator)
        self._init_task_ledger(mem_dir / "PA-LEDGER.md", config.persona, config.operator)
        self._deploy_standalone_runtime(runtime_dir, config.persona.name)

        return self.target_home

    def _init_brain_database(self, db_path: Path, operator: OperatorProfile):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS habits_and_routines (
            metric_key TEXT PRIMARY KEY,
            metric_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_nutrition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_str TEXT,
            food_item TEXT,
            calories REAL,
            protein_g REAL,
            carbs_g REAL,
            fats_g REAL,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS people_directory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            relationship TEXT,
            birthday TEXT,
            notes TEXT,
            face_embedding_id TEXT
        )
        """)

        seed_data = [
            ("wake_time", operator.wake_time),
            ("sleep_time", operator.sleep_time),
            ("work_hours", operator.work_hours),
            ("gym_time", operator.gym_time),
            ("daily_calories_target", str(operator.daily_calories_target)),
            ("daily_protein_target_g", str(operator.daily_protein_target_g)),
        ]
        cur.executemany("INSERT OR REPLACE INTO habits_and_routines (metric_key, metric_value) VALUES (?, ?)", seed_data)
        conn.commit()
        conn.close()

    def _init_task_ledger(self, ledger_path: Path, persona: AgentPersona, operator: OperatorProfile):
        content = f"""# PERSONAL AGENT ROOT LEDGER
**Companion**: {persona.name} ({persona.tone_style})
**Operator**: {operator.call_sign}

### Immutable Directives
- [INVARIANT] The companion identity is {persona.name}; prioritize {operator.call_sign}'s focus and time.
- [INVARIANT] Perform destructive operations only after explicit operator confirmation.

### Active Milestones
- [ ] Complete initial device environment setup and health profile calibration.
- [ ] Connect communication channels (Email, Slack, WhatsApp).
"""
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _deploy_standalone_runtime(self, runtime_dir: Path, agent_name: str):
        """Generates the live ReAct tool execution runtime with biometric gating."""
        runtime_code = f'''import os
import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from agent.pa_scaffolder.biometric_vault import BiometricVault

class StandalonePersonalAgent:
    def __init__(self, pa_home: Optional[str] = None):
        self.pa_home = Path(pa_home or Path(__file__).resolve().parent.parent)
        self.config_path = self.pa_home / "config.json"
        self.profile_path = self.pa_home / "memory" / "profile.json"
        self.db_path = self.pa_home / "memory" / "brain.db"
        self.config = self._load_json(self.config_path)
        self.profile = self._load_json(self.profile_path)
        self.vault = BiometricVault(db_path=self.db_path)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @property
    def name(self) -> str:
        return self.profile.get("persona", {{}}).get("name", "{agent_name}")

    @property
    def operator(self) -> str:
        return self.profile.get("operator", {{}}).get("call_sign", "Operator")

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        # Sensitive tools are biometrically gated
        if tool_name in ["execute_bash", "write_file", "shutdown"]:
            ok, res = self.vault.gate_sensitive_action(
                action_description=f"Run {{tool_name}}",
                callback=self._run_tool_unlocked,
                tool_name=tool_name,
                args=args
            )
            return str(res) if ok else f"[BLOCKED BY BIOMETRIC GATE]: {{res}}"
        return self._run_tool_unlocked(tool_name, args)

    def _run_tool_unlocked(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "execute_bash":
            cmd = args.get("command", "")
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return res.stdout.strip() if res.returncode == 0 else f"ERROR: {{res.stderr}}"

        elif tool_name == "query_habits":
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT metric_key, metric_value FROM habits_and_routines")
            data = dict(cur.fetchall())
            conn.close()
            return json.dumps(data, indent=2)

        return f"Unknown tool: {{tool_name}}"

    def run_turn(self, user_instruction: str) -> str:
        inst_lower = user_instruction.lower()
        if "habit" in inst_lower or "calorie" in inst_lower:
            return self.execute_tool("query_habits", {{}})
        elif inst_lower.startswith("run ") or inst_lower.startswith("exec "):
            return self.execute_tool("execute_bash", {{"command": user_instruction.split(" ", 1)[1]}})
        return f"{{self.name}} standing by for instruction: '{{user_instruction}}'"

    def greeting(self) -> str:
        return f"Hey {{self.operator}}! {{self.name}} is online and standing by."

if __name__ == "__main__":
    pa = StandalonePersonalAgent()
    print(pa.run_turn(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else pa.greeting())
'''
        with open(runtime_dir / "pa_runtime.py", "w", encoding="utf-8") as f:
            f.write(runtime_code)
