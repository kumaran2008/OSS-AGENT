import os
import sys
import json
import sqlite3
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List

class StandalonePersonalAgent:
    """
    Live cognitive engine for the Personal Agent.
    Executes tasks, selects system tools, and manages local state.
    """
    def __init__(self, pa_home: Optional[str] = None):
        self.pa_home = Path(pa_home or Path(__file__).resolve().parent.parent)
        self.config_path = self.pa_home / "config.json"
        self.profile_path = self.pa_home / "memory" / "profile.json"
        self.db_path = self.pa_home / "memory" / "brain.db"
        self.config = self._load_json(self.config_path)
        self.profile = self._load_json(self.profile_path)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self, path: Path, data: Dict[str, Any]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @property
    def name(self) -> str:
        return self.profile.get("persona", {}).get("name", "Hype")

    @property
    def operator(self) -> str:
        return self.profile.get("operator", {}).get("call_sign", "Operator")

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Executes authorized host OS tools."""
        if tool_name == "execute_bash":
            cmd = args.get("command", "")
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                out = res.stdout if res.returncode == 0 else f"ERROR: {res.stderr}"
                return out.strip() or "[Command executed with no output]"
            except Exception as e:
                return f"Execution error: {e}"

        elif tool_name == "read_file":
            filepath = Path(args.get("filepath", ""))
            if not filepath.exists():
                return f"Error: File {filepath} does not exist."
            return filepath.read_text(encoding="utf-8", errors="replace")[:3000]

        elif tool_name == "query_habits":
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT metric_key, metric_value FROM habits_and_routines")
            rows = dict(cur.fetchall())
            conn.close()
            return json.dumps(rows, indent=2)

        return f"Unknown tool: {tool_name}"

    def run_turn(self, user_instruction: str) -> str:
        """Processes user input through local inference or tool calls."""
        # Simple intent routing for common local commands
        inst_lower = user_instruction.lower()
        if "habit" in inst_lower or "calorie" in inst_lower or "schedule" in inst_lower:
            habits = self.execute_tool("query_habits", {})
            return f"Here is what I have in our cognitive brain for your schedule and targets:\n{habits}"

        elif inst_lower.startswith("run ") or inst_lower.startswith("exec "):
            cmd = user_instruction.split(" ", 1)[1]
            out = self.execute_tool("execute_bash", {"command": cmd})
            return f"Executed `{cmd}`:\n{out}"

        # Fallback conversational response
        return f"{self.name} received your instruction: '{user_instruction}'. Ready for next task."

    def greeting(self) -> str:
        return f"Hey {self.operator}! {self.name} is online and standing by. What are we building today?"

if __name__ == "__main__":
    pa = StandalonePersonalAgent()
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(pa.run_turn(query))
    else:
        print(pa.greeting())
