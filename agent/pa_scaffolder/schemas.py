import os
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
from pathlib import Path


@dataclass
class AgentPersona:
    name: str = "Hype"
    wake_word: str = "hype"
    tone_style: str = "Supportive & High Energy"
    voice_profile: str = "dynamic-expressive-1"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentPersona":
        return cls(
            name=data.get("name", "Hype"),
            wake_word=data.get("wake_word", data.get("name", "hype").lower()),
            tone_style=data.get("tone_style", "Supportive & High Energy"),
            voice_profile=data.get("voice_profile", "dynamic-expressive-1")
        )


@dataclass
class OperatorProfile:
    call_sign: str = "Operator"
    wake_time: str = "07:00"
    sleep_time: str = "23:00"
    work_hours: str = "09:00 - 18:00"
    gym_time: str = "18:30 - 19:30"
    daily_calories_target: int = 2200
    daily_protein_target_g: int = 150
    preferred_ide: str = "vscode"
    preferred_shell: str = "bash"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperatorProfile":
        return cls(
            call_sign=data.get("call_sign", "Operator"),
            wake_time=data.get("wake_time", "07:00"),
            sleep_time=data.get("sleep_time", "23:00"),
            work_hours=data.get("work_hours", "09:00 - 18:00"),
            gym_time=data.get("gym_time", "18:30 - 19:30"),
            daily_calories_target=int(data.get("daily_calories_target", 2200)),
            daily_protein_target_g=int(data.get("daily_protein_target_g", 150)),
            preferred_ide=data.get("preferred_ide", "vscode"),
            preferred_shell=data.get("preferred_shell", "bash")
        )


@dataclass
class InferenceConfig:
    engine: str = "openrouter"               # "openrouter" | "direct_api" | "app_automation" | "local_ollama"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: Optional[str] = None
    model: str = "anthropic/claude-3.5-sonnet"
    app_mode: bool = False
    app_target: str = "chatgpt"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InferenceConfig":
        return cls(
            engine=data.get("engine", "openrouter"),
            base_url=data.get("base_url", "https://openrouter.ai/api/v1"),
            api_key=data.get("api_key"),
            model=data.get("model", "anthropic/claude-3.5-sonnet"),
            app_mode=bool(data.get("app_mode", False)),
            app_target=data.get("app_target", "chatgpt")
        )


@dataclass
class PersonalAgentConfig:
    version: str = "1.0.0"
    created_at: str = "2026-09"
    revision: int = 1
    persona: AgentPersona = field(default_factory=AgentPersona)
    operator: OperatorProfile = field(default_factory=OperatorProfile)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    pa_home: str = str(Path.home() / ".personal_agent")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalAgentConfig":
        return cls(
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at", "2026-09"),
            revision=data.get("revision", 1),
            persona=AgentPersona.from_dict(data.get("persona", {})),
            operator=OperatorProfile.from_dict(data.get("operator", {})),
            inference=InferenceConfig.from_dict(data.get("inference", {})),
            pa_home=data.get("pa_home", str(Path.home() / ".personal_agent"))
        )
