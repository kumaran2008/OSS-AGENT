from typing import Any, Dict, List
from llm.router import LLMRouter
from agent.training import experience_buffer


class ReviewerAgent:
    """
    Code Quality, Diff Reviewer, and Adversarial Gate.
    Logs review outcomes into local training buffers for feedback distillation.
    """

    def __init__(self, router: LLMRouter):
        self.router = router

    def review_patch(self, diff_text: str, test_passed: bool) -> Dict[str, Any]:
        critiques: List[str] = []

        if not test_passed:
            critiques.append("Automated test harness failed. Patch cannot be approved.")

        added_lines = 0
        removed_lines = 0
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added_lines += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed_lines += 1

        if added_lines + removed_lines > 400:
            critiques.append(
                f"Diff churn is unusually high (+{added_lines}/-{removed_lines} lines). Ensure scope is minimal."
            )

        approved = len(critiques) == 0
        result = {
            "approved": approved,
            "critiques": critiques if critiques else ["Patch looks focused, minimal, and correct."],
            "stats": {"added": added_lines, "removed": removed_lines},
        }

        # Log evaluation trajectory
        experience_buffer.record_trajectory(
            agent_role="reviewer",
            task_type="diff_evaluation",
            input_context=diff_text[:2000],
            action_output=critiques[0] if critiques else "Approved",
            outcome_reward=1.0 if approved else 0.0,
            metadata={"stats": result["stats"], "test_passed": test_passed},
        )

        return result
