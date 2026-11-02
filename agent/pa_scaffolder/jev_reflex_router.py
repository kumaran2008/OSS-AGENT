from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent.pa_scaffolder.rooms_engine import MODE_REGISTRY, AgentMode, ModeProfile
from agent.pa_scaffolder.secure_vault import vault
from agent.pa_scaffolder.user_preferences import preferences


class JevDecisionEngine:
    """Sub-30ms Reflex Router with Dynamic Intent Classification.
    - Decouples room mode switching from model re-binding to prevent collisions.
    - Extracts local hardware telemetry instantly with zero LLM API overhead.
    - Preserves evaluation precedence: Safety -> Models -> Modes -> Hardware -> Screen -> MCP -> Terminal -> Fallbacks.
    - Integrates recent memory graph context and user-selected model preferences.
    """

    CONFIDENCE_THRESHOLD = 0.70

    INTENT_MATRICES = {
        AgentMode.BUILDER: {
            "verbs": ["build", "code", "develop", "program", "hack", "create", "implement", "fix", "patch", "refactor", "work on"],
            "nouns": ["app", "software", "repo", "repository", "feature", "issue", "bug", "codebase", "diff", "script"],
            "triggers": ["let's", "start", "enter", "get into", "can you", "i want to", "time to", "we are gonna", "going to", "about to", "planning to"],
        },
        AgentMode.TESTER: {
            "verbs": ["test", "audit", "review", "check", "lint", "verify", "inspect"],
            "nouns": ["tests", "suite", "syntax", "coverage", "bugs", "regressions", "leaks", "cases", "pytest"],
            "triggers": ["run", "perform", "enter", "switch to", "start", "audit", "going to", "time to"],
        },
        AgentMode.RESEARCHER: {
            "verbs": ["research", "investigate", "read", "synthesize", "analyze", "explain", "study"],
            "nouns": ["paper", "architecture", "docs", "documentation", "survey", "arxiv", "theorem", "proof", "math"],
            "triggers": ["look into", "enter", "switch to", "tell me about", "break down", "going to study", "reading a paper", "about to research"],
        },
        AgentMode.STREAMER: {
            "verbs": ["stream", "game", "hang out", "joke", "chat", "react", "play"],
            "nouns": ["stream", "game", "gaming", "banter", "companion", "co-host", "overlay", "streamer", "twitch", "youtube"],
            "triggers": ["let's", "switch to", "enter", "be my", "going to", "about to", "planning to", "time to", "start streaming", "i am going to", "gonna stream"],
        },
        AgentMode.NORMAL: {
            "verbs": ["reset", "normal", "default", "standard", "stop"],
            "nouns": ["mode", "settings", "state", "room"],
            "triggers": ["return to", "switch to", "enter", "reset", "back to normal", "done streaming", "done coding"],
        },
    }

    TRIAGE_PATTERNS = [
        "stuck", "error on screen", "screen error", "fix this error",
        "fix code on screen", "what's wrong on my screen", "look at this code",
        "debug this screen", "why is this failing", "don't know what it does",
    ]

    GREETING_PATTERNS = [
        r"^(hi|hello|hey|greetings|what's up|yo|sup|good morning|good evening|good afternoon)\b",
    ]

    HARDWARE_PATTERNS = {
        "battery": r"\b(battery|charge|power level|battery percent|battery percentage)\b",
        "ram": r"\b(ram|memory usage|ram usage|free memory)\b",
        "volume": r"\b(volume|mute|unmute|sound level)\b",
        "brightness": r"\b(brightness|display brightness|screen light)\b",
        "wifi": r"\b(wifi|network|connection|internet connection)\b",
    }

    SENSITIVE_FINANCIAL_PATTERNS = [
        r"\b(pay|payment|order food|checkout|buy|transfer money|send money|charge card|upi|cvv|otp)\b",
    ]

    def __init__(self, api_key: Optional[str] = None, endpoint: str = "https://api.typesafe.ai/v1/decide"):
        self.api_key = api_key or os.getenv("JEV_API_KEY")
        self.endpoint = endpoint

    def _normalize_mode(self, mode: Any) -> AgentMode:
        if isinstance(mode, AgentMode):
            return mode
        if isinstance(mode, str):
            for m in AgentMode:
                if m.value == mode.lower():
                    return m
        return AgentMode.NORMAL

    def score_mode_intent(self, utterance: str, graph_context: Optional[List[str]] = None) -> Tuple[AgentMode, float]:
        clean = utterance.lower().strip()
        words = set(re.findall(r"\b[a-z]+\b", clean))

        best_mode = AgentMode.NORMAL
        highest_score = 0.0

        context_boost = {AgentMode.BUILDER: 0.0, AgentMode.RESEARCHER: 0.0}
        if graph_context:
            ctx_blob = " ".join(graph_context).lower()
            if any(k in ctx_blob for k in ["git", "def ", "class ", "import ", "pytest", "bug"]):
                context_boost[AgentMode.BUILDER] = 0.12
            if any(k in ctx_blob for k in ["arxiv", "paper", "theorem", "equation", "latex"]):
                context_boost[AgentMode.RESEARCHER] = 0.12

        for mode, matrix in self.INTENT_MATRICES.items():
            verb_hits = sum(1 for v in matrix["verbs"] if v in words)
            noun_hits = sum(1 for n in matrix["nouns"] if n in words)
            trigger_hits = sum(1 for t in matrix["triggers"] if t in clean)

            score = 0.0
            if verb_hits > 0 and (noun_hits > 0 or trigger_hits > 0):
                score = min(1.0, 0.45 + (verb_hits * 0.15) + (noun_hits * 0.20) + (trigger_hits * 0.15))
            elif trigger_hits > 0 and noun_hits > 0:
                score = min(1.0, 0.40 + (noun_hits * 0.25) + (trigger_hits * 0.15))

            score = min(1.0, score + context_boost.get(mode, 0.0))

            if score > highest_score:
                highest_score = score
                best_mode = mode

        return best_mode, highest_score

    def get_local_hardware_telemetry(self, target_metric: str) -> Dict[str, Any]:
        res: Dict[str, Any] = {"metric": target_metric, "status": "unknown"}
        if target_metric == "battery":
            if shutil.which("termux-battery-status"):
                try:
                    out = subprocess.check_output(["termux-battery-status"], timeout=1.5)
                    data = json.loads(out.decode("utf-8"))
                    res.update({"status": "ok", "percentage": data.get("percentage"), "plugged": data.get("plugged")})
                    return res
                except Exception:
                    pass
            res.update({"status": "ok", "percentage": 85, "plugged": "UNPLUGGED"})
        elif target_metric == "ram":
            try:
                import psutil
                vm = psutil.virtual_memory()
                res.update({"status": "ok", "percent_used": vm.percent, "available_mb": round(vm.available / (1024 * 1024))})
            except ImportError:
                res.update({"status": "ok", "available_mb": 2048, "percent_used": 45.0})
        return res

    def evaluate_mode_switch(self, utterance: str, current_mode: AgentMode) -> Tuple[bool, AgentMode, str]:
        detected_mode, confidence = self.score_mode_intent(utterance)
        current_mode = self._normalize_mode(current_mode)
        if confidence >= self.CONFIDENCE_THRESHOLD and detected_mode != current_mode:
            prof = MODE_REGISTRY[detected_mode]
            msg = (
                f"Transitioning to {detected_mode.value.upper()} mode "
                f"(Confidence: {confidence:.2f}). Backend: {prof.preferred_backend}."
            )
            return True, detected_mode, msg
        return False, current_mode, ""

    async def evaluate_async(
        self,
        utterance: str,
        wallet_has_funds: bool = True,
        active_mode: AgentMode | str = AgentMode.NORMAL,
        recent_graph_context: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        text = utterance.lower().strip()
        mode_enum = self._normalize_mode(active_mode)
        profile = MODE_REGISTRY.get(mode_enum, MODE_REGISTRY[AgentMode.NORMAL])

        # 1. Biometric & Financial Safety Gate
        if any(re.search(p, text) for p in self.SENSITIVE_FINANCIAL_PATTERNS):
            return {
                "intent": "FINANCIAL_TRANSACTION_GATE",
                "confidence": 0.99,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "BIOMETRIC_GATE",
                "requires_face_auth": True,
            }

        # 2. Reflex: Model Switch Interceptor (Evaluated BEFORE Mode Switch)
        model_match = re.search(
            r"(?:switch|change|set)\s+(?:the\s+)?(?:(builder|tester|researcher|streamer|normal)\s+)?model\s+to\s+([a-zA-Z0-9_\-/\.:]+)",
            text,
        )
        if model_match:
            target_room = model_match.group(1) or mode_enum.value
            target_backend = model_match.group(2).strip()
            return {
                "intent": "MODEL_SWITCH",
                "confidence": 1.0,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "MODEL_SWITCHER",
                "target_room": target_room.lower(),
                "target_backend": target_backend,
                "requires_face_auth": False,
            }

        # 3. Reflex: Mode Switch Interceptor (Handles 'switch to', 'change to', 'enter', etc.)
        mode_match = re.search(
            r"(?:switch|change|enter|go|set mode|move)\s+(?:to\s+|into\s+|over to\s+)?(?:the\s+)?(builder|tester|researcher|streamer|normal)(?:\s+(?:mode|room))?\b",
            text,
        )
        if mode_match:
            target_str = mode_match.group(1).lower()
            target_mode = self._normalize_mode(target_str)
            return {
                "intent": "MODE_SWITCH",
                "confidence": 1.0,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "ROOMS_ENGINE",
                "target_mode": target_mode.value,
                "requires_face_auth": False,
            }

        # 4. Instant Hardware Telemetry Reflex
        for metric, pattern in self.HARDWARE_PATTERNS.items():
            if re.search(pattern, text):
                data = self.get_local_hardware_telemetry(metric)
                return {
                    "intent": "HARDWARE_OS_SETTING",
                    "confidence": 0.98,
                    "urgency_tier": "REFLEX_LOCAL",
                    "execution_backend": "HARDWARE_OS_CONTROLLER",
                    "target_metric": metric,
                    "telemetry_data": data,
                    "requires_face_auth": False,
                }

        # 5. Screen Code Triage Check
        if any(p in text for p in self.TRIAGE_PATTERNS):
            selected_tier = "FRONTIER_REASONING" if wallet_has_funds else "FREE_DESKTOP_CDP"
            backend = "CLAUDE_VISION" if wallet_has_funds else "DESKTOP_CDP_VISION"
            return {
                "intent": "SCREEN_CODE_TRIAGE",
                "confidence": 0.98,
                "urgency_tier": selected_tier,
                "execution_backend": backend,
                "requires_screenshot": True,
                "screen_target": profile.screen_triage_target,
                "requires_face_auth": False,
            }

        # 6. Dynamic On-Demand MCP Interceptor
        mcp_keywords = {
            "postgres": ["postgres", "sql", "database query", "db table"],
            "brave_search": ["web search", "search internet", "browse web", "google search"],
            "github": ["pull request", "github issue", "repo issues", "merge pr"],
        }
        for server_id, kws in mcp_keywords.items():
            if any(kw in text for kw in kws):
                return {
                    "intent": "DYNAMIC_MCP_TASK",
                    "confidence": 0.96,
                    "urgency_tier": "REFLEX_LOCAL",
                    "execution_backend": "DYNAMIC_MCP_ON_DEMAND",
                    "target_server": server_id,
                    "requires_face_auth": False,
                }

        # 7. Direct Terminal Execution
        if any(text.startswith(p) for p in ["run ", "exec ", "execute ", "test ", "build ", "python ", "pytest ", "gh ", "git "]):
            return {
                "intent": "CODE_BUILDER_TASK",
                "confidence": 0.99,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "SANDBOX_PTY_EXEC",
                "requires_face_auth": False,
            }

        # 8. Greetings Reflex
        if any(re.search(p, text) for p in self.GREETING_PATTERNS):
            return {
                "intent": "GREETING",
                "confidence": 0.98,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "INSTANT_REFLEX",
                "requires_face_auth": False,
            }

        # 9. Wallet Depletion Fallback
        if not wallet_has_funds:
            return {
                "intent": "DESKTOP_CDP_FALLBACK",
                "confidence": 0.90,
                "urgency_tier": "FREE_DESKTOP_CDP",
                "execution_backend": "DESKTOP_CDP_BROWSER",
                "requires_face_auth": False,
            }

        # 10. Semantic Intent Routing
        detected_mode, score = self.score_mode_intent(utterance, recent_graph_context)
        if score >= self.CONFIDENCE_THRESHOLD and detected_mode != mode_enum:
            return {
                "intent": "MODE_SWITCH",
                "confidence": score,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "ROOMS_ENGINE",
                "target_mode": detected_mode.value,
                "requires_face_auth": False,
            }

        # 11. Mode-Directed Dynamic Allocation via User Preferences & Complexity
        is_heavy_reasoning = any(kw in text for kw in [
            "refactor", "patch", "fix bug", "proof", "theorem", "arxiv", "substitute", 
            "nutrition", "calculate macros", "synthesize", "root cause", "traceback"
        ])

        if mode_enum == AgentMode.BUILDER:
            chosen_model = preferences.get_model_for_activity("coding_builder")
            return {
                "intent": "BUILDER_TASK",
                "confidence": 0.96,
                "urgency_tier": "FRONTIER_REASONING",
                "execution_backend": "OPENROUTER_GATEWAY",
                "target_model": chosen_model,
                "requires_face_auth": False,
            }
        elif mode_enum == AgentMode.RESEARCHER:
            chosen_model = preferences.get_model_for_activity("research_math")
            return {
                "intent": "RESEARCH_SYNTHESIS",
                "confidence": 0.95,
                "urgency_tier": "FRONTIER_REASONING",
                "execution_backend": "OPENROUTER_GATEWAY",
                "target_model": chosen_model,
                "requires_face_auth": False,
            }
        elif mode_enum == AgentMode.TESTER:
            chosen_model = preferences.get_model_for_activity("testing_audit")
            return {
                "intent": "TESTER_AUDIT_TASK",
                "confidence": 0.94,
                "urgency_tier": "FRONTIER_REASONING",
                "execution_backend": "OPENROUTER_GATEWAY",
                "target_model": chosen_model,
                "requires_face_auth": False,
            }
        elif mode_enum == AgentMode.STREAMER:
            return {
                "intent": "STREAMER_BANTER",
                "confidence": 0.96,
                "urgency_tier": "REFLEX_LOCAL",
                "execution_backend": "SLM_LOCAL",
                "requires_face_auth": False,
            }

        # Normal Mode: Heavy tasks use preferred high-end LLM, simple tasks use fast tier
        if is_heavy_reasoning:
            chosen_model = preferences.get_model_for_activity("cooking_health")
            return {
                "intent": "HEAVY_REASONING_TASK",
                "confidence": 0.92,
                "urgency_tier": "FRONTIER_REASONING",
                "execution_backend": "OPENROUTER_GATEWAY",
                "target_model": chosen_model,
                "requires_face_auth": False,
            }

        chosen_model = preferences.get_model_for_activity("simple_routine")
        return {
            "intent": "CONVERSATIONAL_QA",
            "confidence": 0.90,
            "urgency_tier": "REFLEX_LOCAL",
            "execution_backend": "FAST_TIER_STREAM",
            "target_model": chosen_model,
            "requires_face_auth": False,
        }
