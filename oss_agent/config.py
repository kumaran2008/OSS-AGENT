from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

CONFIG_PATH = Path.home() / ".oss_agent" / "agent_config.json"

class AgentSettings(BaseModel):
    agent_name: str = "Jarvis"
    wake_word: str = "jarvis"
    voice_continuous_listen: bool = True
    jev_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    task_model_mapping: Dict[str, str] = Field(default_factory=lambda: {
        "reasoning": "anthropic/claude-3.7-sonnet",
        "coding": "qwen/qwen-2.5-coder-32b-instruct",
        "general": "deepseek/deepseek-chat",
        "quick_chat": "deepseek/deepseek-chat"
    })
    token_usage_tracker: Dict[str, int] = Field(default_factory=dict)
    first_run_timestamp: float = 0.0

def load_settings() -> AgentSettings:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return AgentSettings.model_validate_json(f.read())
        except Exception:
            pass
    return AgentSettings()

def save_settings(settings: AgentSettings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(settings.model_dump_json(indent=2))
