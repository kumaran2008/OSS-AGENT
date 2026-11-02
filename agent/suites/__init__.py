from __future__ import annotations

import importlib
from typing import Any

_SUITE_MAP = {
    "builder_suite": ("agent.suites.builder_cursor_lovable", "builder_suite"),
    "computer_app_control_suite": ("agent.suites.computer_app_control", "computer_app_control_suite"),
    "researcher_suite": ("agent.suites.researcher_lab_hub", "researcher_suite"),
    "personal_assistant_suite": ("agent.suites.personal_assistant", "personal_assistant_suite"),
    "streamer_gamer_suite": ("agent.suites.streamer_gamer_broadcast", "streamer_gamer_suite"),
    "news_intelligence_suite": ("agent.suites.news_intelligence", "news_intelligence_suite"),
    "reliability_shadow_service": ("agent.suites.reliability_and_shadow", "reliability_shadow_service"),
}


def __getattr__(name: str) -> Any:
    if name in _SUITE_MAP:
        mod_name, attr_name = _SUITE_MAP[name]
        mod = importlib.import_module(mod_name)
        return getattr(mod, attr_name)
    raise AttributeError(f"module 'agent.suites' has no attribute {name!r}")
