import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

class StandalonePersonalAgent:
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

    def update_agent_persona(
        self,
        new_name: Optional[str] = None,
        new_tone: Optional[str] = None,
        new_call_sign: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        In-flight tool allowing the agent or user to rename and recalibrate
        identity without reinstalling or restarting the process.
        """
        if new_name:
            self.profile.setdefault("persona", {})["name"] = new_name
            self.profile["persona"]["wake_word"] = new_name.lower()
            self.config.setdefault("persona", {})["name"] = new_name
            self.config["persona"]["wake_word"] = new_name.lower()

        if new_tone:
            self.profile.setdefault("persona", {})["tone_style"] = new_tone
            self.config.setdefault("persona", {})["tone_style"] = new_tone

        if new_call_sign:
            self.profile.setdefault("operator", {})["call_sign"] = new_call_sign
            self.config.setdefault("operator", {})["call_sign"] = new_call_sign

        self._save_json(self.profile_path, self.profile)
        self._save_json(self.config_path, self.config)
        return {
            "status": "SUCCESS",
            "active_name": self.name,
            "operator": self.operator,
            "tone": self.profile.get("persona", {}).get("tone_style")
        }

    def greeting(self) -> str:
        return f"Hey {self.operator}! {self.name} is online and standing by. What are we building today?"

if __name__ == "__main__":
    pa = StandalonePersonalAgent()
    print(pa.greeting())
