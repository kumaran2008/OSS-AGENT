from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class WorkflowSessionManager:
    """Dynamic Multi-Turn Stateful Workflow Coordinator.
    Supports any recipe, hardware procedure, or multi-stage task without hardcoded dishes.
    """

    def __init__(self):
        self.active_session: Optional[Dict[str, Any]] = None
        self.step_index: int = 0
        self.steps: List[str] = []
        self.substitutions: Dict[str, str] = {}
        self.workflow_title: str = ""

    def is_active(self) -> bool:
        return self.active_session is not None and self.active_session.get("is_active", False)

    def start_recipe(
        self,
        dish: str,
        ingredients: Optional[List[str]] = None,
        custom_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Initializes a stateful session for ANY dish or procedure."""
        self.workflow_title = dish.strip()
        self.step_index = 0
        self.substitutions = {}

        if custom_steps and len(custom_steps) > 0:
            self.steps = custom_steps
        else:
            self.steps = [
                f"Step 1 for {self.workflow_title}: Prep and measure your core ingredients, aromatics, and base components.",
                f"Step 2 for {self.workflow_title}: Heat your primary vessel and sauté the aromatics until fragrant.",
                f"Step 3 for {self.workflow_title}: Incorporate the main body and seasonings; simmer or cook until tender.",
                f"Step 4 for {self.workflow_title}: Adjust seasoning, garnish, and rest before serving.",
            ]

        self.active_session = {
            "type": "workflow",
            "title": self.workflow_title,
            "ingredients": ingredients or [],
            "total_steps": len(self.steps),
            "is_active": True,
            "started_at": time.time(),
        }
        return self.active_session

    def record_substitution(self, missing_item: str, replacement: str) -> str:
        self.substitutions[missing_item] = replacement
        return f"Noted substitution for {self.workflow_title}: using {replacement} in place of {missing_item}."

    def next_step(self) -> str:
        if not self.is_active():
            return "No active workflow session."

        if self.step_index < len(self.steps):
            instruction = self.steps[self.step_index]
            self.step_index += 1
            return instruction

        title = self.workflow_title
        self.complete_workflow()
        return f"Workflow complete! Your {title} is finished and ready, sir."

    def complete_workflow(self) -> None:
        if self.active_session:
            self.active_session["is_active"] = False
        self.active_session = None
        self.step_index = 0

    def reset(self) -> None:
        self.complete_workflow()

    def get_session(self) -> Optional[Dict[str, Any]]:
        return self.active_session


workflow_manager = WorkflowSessionManager()
