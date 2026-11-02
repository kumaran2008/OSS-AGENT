from __future__ import annotations

from typing import Any, Dict
from agent.memory_graph.memory_service import unified_memory_service


class BehavioralPreferenceLearner:
    """Section 4.3 & 10: Behavioral Preference Learning with Repetition & Confidence Gating."""

    def record_interaction_habit(self, behavior_key: str, observed_value: str, explicit_confirmation: bool = False) -> Dict[str, Any]:
        return unified_memory_service.observe_behavioral_signal(
            behavior_key=behavior_key,
            observed_preference=observed_value,
            explicit_user_confirmation=explicit_confirmation,
        )


preference_learner = BehavioralPreferenceLearner()
