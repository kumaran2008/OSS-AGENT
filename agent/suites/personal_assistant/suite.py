from __future__ import annotations

from typing import Any, Dict, Optional
from agent.memory_graph.memory_service import unified_memory_service
from agent.suites.personal_assistant.biometric_and_nutrition import biometric_nutrition_assistant
from agent.suites.personal_assistant.preference_learning import preference_learner
from agent.suites.personal_assistant.temporal_planner import temporal_planner


class PersonalAssistantSuite:
    """Section 10: Personal Assistant (Normal Mode Jarvis) Suite Coordinator."""

    def process_natural_conversation_turn(
        self,
        user_utterance: str,
        active_task_state: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_dep = temporal_planner.parse_activity_and_reminder(user_utterance)
        reminder_armed = None
        if parsed_dep is not None:
            reminder_armed = temporal_planner.arm_conditional_reminder(
                task_dependency=parsed_dep["activity"],
                reminder_text=parsed_dep["reminder_text"],
            )

        scoped_mems = unified_memory_service.retrieve_scoped_memories(user_utterance)
        return {
            "utterance": user_utterance,
            "enforced_namespaces": scoped_mems["enforced_namespaces"],
            "conditional_reminder_armed": reminder_armed.to_dict() if reminder_armed else None,
            "relevant_memories_recalled": len(scoped_mems["results"]),
            "recalled_memories": scoped_mems["results"],
            "response_mode": "EMPATHETIC_PEER_COMPANION",
        }


personal_assistant_suite = PersonalAssistantSuite()
