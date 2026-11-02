from __future__ import annotations

from typing import Dict, List, Set

# Section 4.2: All 14 Strict Memory Namespaces
VALID_MEMORY_NAMESPACES: Dict[str, str] = {
    "ambitions_and_goals": "Long-term startup goals, YC application milestones, career targets",
    "coding_and_architecture": "Repository structure, Python conventions, active bugs, architectural decisions",
    "research_knowledge": "Academic papers, equations, datasets, empirical benchmarks, citations",
    "health_and_biometrics": "Sleep stages, resting heart rate, HRV, recovery scores, workouts",
    "nutrition_and_diet": "Meal logs, calorie/macro ranges, food allergies (e.g., peanuts/groundnuts), hydration",
    "schedule_and_alarms": "Alarms, timers, calendar events, conditional task-linked reminders",
    "social_and_relationships": "Family members (e.g., brother Karthik/Rahul), colleagues, contact roles",
    "education_and_learning": "Study topics, expertise calibration levels, learning progress",
    "financial_and_business": "API budgets, cloud costs, invoices, business metrics",
    "digital_accounts": "Connected OAuth/MCP services, non-secret account identifiers",
    "communication_preferences": "Preferred response length, tone, explanation depth",
    "entertainment_and_interests": "Games, streams, music, media preferences",
    "device_and_environment": "Workstation hardware profiles, OS environment, IoT devices",
    "travel_and_locations": "Timezone (IST), locations, commute and travel plans",
}

SENSITIVE_NAMESPACES: Set[str] = {
    "health_and_biometrics",
    "nutrition_and_diet",
    "financial_and_business",
    "social_and_relationships",
    "digital_accounts",
}

VALID_MEMORY_TYPES: Set[str] = {
    "EPISODIC",     # What happened (e.g., worked on Builder Suite yesterday)
    "SEMANTIC",     # Stable knowledge & facts
    "PROCEDURAL",   # How to perform a workflow or testing routine
    "PREFERENCE",   # How the user likes things done (requires repetition/confirmation)
    "PROJECT",      # Active work, branch, architecture decisions, TODOs
}


def validate_namespaces(namespaces: List[str]) -> List[str]:
    cleaned = [ns.replace("#vault/", "").strip().lower() for ns in namespaces]
    valid = [ns for ns in cleaned if ns in VALID_MEMORY_NAMESPACES]
    return valid if valid else ["coding_and_architecture"]
