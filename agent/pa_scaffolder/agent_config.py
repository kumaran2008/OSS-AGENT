from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class CallableStr(str):
    def __call__(self) -> str:
        return self


class CallableList(list):
    def __call__(self) -> list:
        return self


class AgentConfig:
    """Manages agent identity, vocal persona, wake words, and inference settings."""

    CONFIG_PATH = Path("workspace/pa_config.json")
    RENAME_PATTERN = re.compile(
        r"(?:change\s+(?:your\s+)?name\s+to|rename\s+(?:yourself\s+)?to|"
        r"from\s+now\s+on\s+(?:your\s+name\s+is|call\s+yourself))\s+([a-zA-Z0-9_\-]+)",
        re.IGNORECASE,
    )

    def __init__(self, default_name: str = "Jarvis"):
        self.data: Dict[str, Any] = {
            "agent_name": default_name,
            "voice_name": "am_adam",
            "voice_speed": 1.0,
            "streaming_mode": "sentence",
            "active_backend": "deepseek_flash",
            "acknowledgments": ["Yes?", "I'm listening.", "Go ahead.", "Online.", "Ready."],
            "wake_words": [default_name.lower(), f"hey {default_name.lower()}"],
        }
        self._load()
        if not self.data.get("agent_name"):
            self.data["agent_name"] = default_name

    def _load(self) -> None:
        if self.CONFIG_PATH.exists():
            try:
                content = json.loads(self.CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(content, dict):
                    self.data.update(content)
            except Exception:
                pass

    def _save(self) -> None:
        try:
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.CONFIG_PATH.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @property
    def agent_name(self) -> str:
        return CallableStr(self.data.get("agent_name", "Jarvis"))

    @property
    def voice_name(self) -> str:
        return CallableStr(self.data.get("voice_name", "am_adam"))

    @property
    def voice_speed(self) -> float:
        return float(self.data.get("voice_speed", 1.0))

    @property
    def streaming_mode(self) -> str:
        return CallableStr(self.data.get("streaming_mode", "sentence"))

    @property
    def active_backend(self) -> str:
        return CallableStr(self.data.get("active_backend", "deepseek_flash"))

    @active_backend.setter
    def active_backend(self, value: str) -> None:
        self.data["active_backend"] = str(value)
        self._save()

    @property
    def wake_words(self) -> List[str]:
        name = str(self.agent_name).lower()
        custom = self.data.get("wake_words", [])
        defaults = [name, f"hey {name}"]
        for d in defaults:
            if d not in custom:
                custom.append(d)
        return CallableList(custom)

    @property
    def acknowledgments(self) -> List[str]:
        default_acks = ["Yes?", "I'm listening.", "Go ahead.", "Online.", "Ready."]
        return CallableList(self.data.get("acknowledgments", default_acks))

    def set_agent_name(self, new_name: str) -> None:
        clean = new_name.strip().capitalize()
        self.data["agent_name"] = clean
        self.data["wake_words"] = [clean.lower(), f"hey {clean.lower()}"]
        self._save()

    def set_backend(self, backend_key: str) -> None:
        self.data["active_backend"] = backend_key
        self._save()

    def check_rename_command(self, transcript: str) -> Tuple[bool, Optional[str], Optional[str]]:
        match = self.RENAME_PATTERN.search(transcript)
        if match:
            new_name = match.group(1).strip().capitalize()
            self.set_agent_name(new_name)
            msg = f"Name updated to {new_name}. Wake word is now 'Hey {new_name}'."
            return True, new_name, msg
        return False, None, None

    def check_backend_switch_command(self, transcript: str) -> Tuple[bool, Optional[str]]:
        clean = transcript.lower().strip()
        backends = {
            "deepseek": "deepseek_flash",
            "google": "google_live",
            "gemini": "google_live",
            "slm": "local_slm",
            "cdp": "desktop_cdp",
        }
        for trigger, backend in backends.items():
            if f"switch to {trigger}" in clean or f"use {trigger}" in clean:
                self.set_backend(backend)
                return True, f"Inference backend set to {backend}."
        return False, None

    def build_wake_pattern(self):
        import re
        w = getattr(self, 'wake_word', None) or getattr(self, 'assistant_name', 'friday') or 'friday'
        return re.compile(rf'\b(?:{re.escape(str(w).lower())}|friday|jarvis|hey\s+friday)\b', re.IGNORECASE)
