from __future__ import annotations

from typing import Any, Dict, List
from agent.kernel.jev_ai_system1 import jev_ai_brain


class AdaptiveExpertiseCalibrator:
    """Section 6.2: Adaptive Expertise Calibrator (Beginner to Specialist Research)."""

    LEVELS = {
        1: "BEGINNER",
        2: "INTERMEDIATE",
        3: "ADVANCED_UNDERGRADUATE",
        4: "GRADUATE",
        5: "SPECIALIST_RESEARCH",
    }

    def calibrate_user_expertise(self, topic: str, user_background_query: str) -> Dict[str, Any]:
        q_cal = {
            "expertise_level": {
                "type": "score",
                "levels": [1, 2, 3, 4, 5],
                "high_signals": ["phd", "dissertation", "eigenvalue", "manifold", "asymptotic", "tensor", "postdoc", "proof", "convex optimization"],
                "mid_signals": ["undergraduate", "bachelors", "calculus", "linear algebra", "python", "api"],
            }
        }
        res = jev_ai_brain.evaluate_primitives(f"Topic: {topic} | User Background: {user_background_query}", q_cal)
        norm_score = res["expertise_level"].value
        lvl_idx = max(1, min(5, int(round(norm_score * 4.0 + 1.0))))
        level_name = self.LEVELS[lvl_idx]

        return {
            "topic": topic,
            "calibrated_level_index": lvl_idx,
            "calibrated_level_name": level_name,
            "confidence": res["expertise_level"].confidence,
            "explanation_strategy": (
                "Start from first principles, visual mental models, and intuitive analogies."
                if lvl_idx <= 2
                else ("Introduce formal mathematical definitions, rigorous proofs, and primary literature citations.")
            ),
        }


expertise_calibrator = AdaptiveExpertiseCalibrator()
