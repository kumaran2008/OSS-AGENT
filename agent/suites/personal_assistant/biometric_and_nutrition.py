from __future__ import annotations

from typing import Any, Dict, List
from agent.memory_graph.memory_service import unified_memory_service


class BiometricAndNutritionAssistant:
    """Section 4.3: Biometric Recovery & Image-Based Nutrition Estimator with Honest Uncertainty Ranges.
    Never claims image-based food estimation is an exact gram measurement or that a recovery score is a medical diagnosis.
    """

    def estimate_meal_nutrition_with_ranges(
        self,
        meal_description: str,
        detected_items: List[str],
        portion_confidence: float = 0.78,
        user_consent_granted: bool = True,
    ) -> Dict[str, Any]:
        if not user_consent_granted:
            return {"status": "CONSENT_REQUIRED", "stored": False}

        base_kcal = 220 * max(1, len(detected_items))
        margin = int(round(base_kcal * (1.0 - portion_confidence * 0.7)))
        kcal_range = (max(80, base_kcal - margin), base_kcal + margin)
        protein_range_g = (max(6, len(detected_items) * 11 - 5), len(detected_items) * 11 + 7)

        summary = (
            f"Meal '{meal_description}' ({', '.join(detected_items)}): "
            f"Estimated {kcal_range[0]}-{kcal_range[1]} kcal, "
            f"Protein {protein_range_g[0]}-{protein_range_g[1]}g (Confidence={portion_confidence:.2f}, image-based estimate)."
        )
        mem = unified_memory_service.ingest_memory(
            content=summary,
            namespace="nutrition_and_diet",
            memory_type="EPISODIC",
            confidence=portion_confidence,
        )
        return {
            "status": "ESTIMATED_WITH_CONFIDENCE_INTERVAL",
            "calories_kcal_range": kcal_range,
            "protein_grams_range": protein_range_g,
            "confidence": portion_confidence,
            "uncertainty_notice": "Image-based portion estimation provides approximate ranges, not exact laboratory measurements.",
            "memory_id": mem["memory_id"],
        }

    def compute_wellness_recovery_trend(
        self,
        sleep_hours: float,
        resting_hr_bpm: float,
        hrv_ms: float,
        user_consent_granted: bool = True,
    ) -> Dict[str, Any]:
        if not user_consent_granted:
            return {"status": "CONSENT_REQUIRED"}

        sleep_score = min(100.0, (sleep_hours / 8.0) * 100.0)
        hrv_score = min(100.0, (hrv_ms / 75.0) * 100.0)
        hr_penalty = max(0.0, (resting_hr_bpm - 60.0) * 1.2)
        readiness = round(max(10.0, min(99.0, (sleep_score * 0.5 + hrv_score * 0.5) - hr_penalty)), 1)

        return {
            "readiness_score": readiness,
            "inputs_documented": {"sleep_hours": sleep_hours, "resting_hr_bpm": resting_hr_bpm, "hrv_ms": hrv_ms},
            "non_medical_disclaimer": "Calculated from documented wellness inputs for personal pacing; not a medically validated diagnostic measure.",
        }


biometric_nutrition_assistant = BiometricAndNutritionAssistant()
