from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class UserPreferences:
    """Manages user-selected LLM mappings for every workstation activity."""

    PREFS_PATH = Path("workspace/user_preferences.json")

    DEFAULT_PREFERENCES: Dict[str, Any] = {
        # Activity -> Preferred LLM Model Identifier
        "coding_builder": "anthropic/claude-3.7-sonnet",     # AST refactoring, heavy coding
        "testing_audit": "deepseek/deepseek-coder",          # Test execution, flaky audits
        "research_math": "anthropic/claude-3.7-sonnet:thinking", # Proofs, ArXiv literature
        "cooking_health": "anthropic/claude-3.7-sonnet",    # Recipe adaptation, macros
        "voice_daily": "gemini-2.0-flash-exp",              # Real-time spoken dialogue
        "simple_routine": "deepseek/deepseek-chat",         # Fast conversational banter
        # Budget & Wallet
        "wallet_provider": "openrouter",                     # 'openrouter' or 'direct'
        "token_budget_alert_threshold": 1.00,                # Warn when balance drops below $1.00
        "max_per_query_budget": 0.25,                        # Hard limit per reasoning turn
    }

    def __init__(self):
        self.PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.prefs: Dict[str, Any] = self.DEFAULT_PREFERENCES.copy()
        self.load()

    def load(self) -> None:
        if self.PREFS_PATH.exists():
            try:
                data = json.loads(self.PREFS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.prefs.update(data)
            except Exception:
                pass

    def save(self) -> None:
        self.PREFS_PATH.write_text(json.dumps(self.prefs, indent=2), encoding="utf-8")

    def get_model_for_activity(self, activity: str) -> str:
        return self.prefs.get(activity, self.prefs["simple_routine"])

    def set_model_for_activity(self, activity: str, model_id: str) -> None:
        self.prefs[activity] = model_id.strip()
        self.save()

    def get_all(self) -> Dict[str, Any]:
        return self.prefs.copy()


preferences = UserPreferences()
