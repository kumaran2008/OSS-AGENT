from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.native import native_accel


@dataclass
class JEVModelSpec:
    model_id: str
    provider: str          # "local" | "deepseek" | "google" | "openai" | "anthropic" | "openrouter"
    tier: int              # 0=Reflex, 1=Fast Universal (DeepSeek V4.1 Flash), 2=Specialist, 3=Apex Frontier
    input_usd_per_1m: float
    output_usd_per_1m: float
    cached_usd_per_1m: float
    coding_quality: float
    reasoning_quality: float
    search_quality: float
    general_quality: float
    context_window: int = 1_000_000
    supports_vision: bool = True
    is_local: bool = False
    is_default_universal: bool = False


class ActionBudgetModelBroker:
    """Universal Dynamic Quality-vs-Budget Model Arbitrator.
    - Default High-Efficiency Universal Backbone:
        * `deepseek-v4.1-flash` ($0.15/1M in, $0.003/1M cached, $0.60/1M out, 1M context)
        * `deepseek-v4-pro` ($0.66/1M in, $0.022/1M cached, $1.98/1M out, 1M context)
    - Universal Registry (`universal_model_registry` in SQLite):
        * Not locked to hardcoded tiers — any model can be added, synced from OpenRouter/env,
          or updated dynamically via empirical execution outcomes (`record_empirical_outcome`).
    - Quality-First Budget Selection:
        * Calculates `required_quality` and `task_budget_usd` from the task's semantic demands.
        * Never compromises quality on Coding, Debugging, Search, or Architecture (`Q_min >= 0.92 - 0.96`).
        * For routine/general tasks where `deepseek-v4.1-flash` already exceeds `required_quality`,
          selects `deepseek-v4.1-flash` so you get 0.93+ quality at 1/20th the cost of Western frontier models.
    """

    DB_PATH = Path("workspace/kernel_governance.db")
    DEFAULT_UNIVERSAL_MODEL = "deepseek-v4.1-flash"
    DEFAULT_APEX_CODING_MODEL = "deepseek-v4-pro"

    DOMAIN_REQUIREMENTS: Dict[str, Dict[str, float]] = {
        "DETERMINISTIC_REFLEX":      {"q_min": 0.99, "default_budget_usd": 0.0,      "target_tier": 0},
        "GENERAL_ROUTINE":           {"q_min": 0.85, "default_budget_usd": 0.0005,   "target_tier": 1},
        "DEEP_SEARCH_RESEARCH":      {"q_min": 0.92, "default_budget_usd": 0.0050,   "target_tier": 2},
        "HIGH_STAKES_CODING_DEBUG":  {"q_min": 0.95, "default_budget_usd": 0.0250,   "target_tier": 3},
        "ARCHITECTURE_REASONING":    {"q_min": 0.96, "default_budget_usd": 0.0500,   "target_tier": 3},
    }

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.max_tokens_per_task = 32000
        self.max_cost_usd_per_task = 0.25
        self.spent_tokens_session = 0
        self.spent_usd_session = 0.0
        self._provider_circuit_open_until: Dict[str, float] = {}
        self._provider_failures: Dict[str, int] = {}
        self._models: Dict[str, JEVModelSpec] = {}
        self._init_db()
        self._seed_universal_registry()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS zero_trust_data_capsules (
                    capsule_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    selected_model TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    sensitivity_tier TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    estimated_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL,
                    secrets_redacted INTEGER NOT NULL,
                    left_device INTEGER NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS universal_model_registry (
                    model_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    tier INTEGER NOT NULL,
                    input_usd_per_1m REAL NOT NULL,
                    output_usd_per_1m REAL NOT NULL,
                    cached_usd_per_1m REAL NOT NULL,
                    coding_quality REAL NOT NULL,
                    reasoning_quality REAL NOT NULL,
                    search_quality REAL NOT NULL,
                    general_quality REAL NOT NULL,
                    context_window INTEGER NOT NULL,
                    supports_vision INTEGER NOT NULL,
                    is_local INTEGER NOT NULL,
                    is_default_universal INTEGER NOT NULL,
                    empirical_calls INTEGER DEFAULT 0,
                    empirical_successes INTEGER DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _seed_universal_registry(self) -> None:
        catalog = [
            # Tier 0: Instant C/Python Deterministic Reflex ($0.00, 0 tokens)
            JEVModelSpec(
                "local:jev-kernel-reflex", "local", 0,
                0.0, 0.0, 0.0,
                0.995, 0.995, 0.995, 0.995,
                context_window=128_000, supports_vision=False, is_local=True,
            ),
            # Default Universal High-Efficiency Backbone: DeepSeek V4.1 Flash (1M context, $0.15/$0.60, $0.003 cached)
            JEVModelSpec(
                "deepseek-v4.1-flash", "deepseek", 1,
                0.15, 0.60, 0.003,
                0.92, 0.92, 0.93, 0.94,
                context_window=1_000_000, supports_vision=True, is_default_universal=True,
            ),
            # Other Eco/Fast Cloud Alternatives
            JEVModelSpec(
                "gemini-2.5-flash-lite", "google", 1,
                0.10, 0.40, 0.025,
                0.82, 0.83, 0.86, 0.90,
                context_window=1_000_000, supports_vision=True,
            ),
            JEVModelSpec(
                "gpt-4o-mini", "openai", 1,
                0.15, 0.60, 0.075,
                0.83, 0.84, 0.86, 0.89,
                context_window=128_000, supports_vision=True,
            ),
            # Tier 2: Balanced Specialist & Deep-Search Synthesis Models
            JEVModelSpec(
                "deepseek-v4.1-flash-think", "deepseek", 2,
                0.15, 0.60, 0.003,
                0.945, 0.95, 0.955, 0.95,
                context_window=1_000_000, supports_vision=True, is_default_universal=True,
            ),
            JEVModelSpec(
                "gemini-2.5-flash", "google", 2,
                0.15, 0.60, 0.037,
                0.91, 0.92, 0.945, 0.94,
                context_window=1_000_000, supports_vision=True,
            ),
            JEVModelSpec(
                "claude-3-7-sonnet", "anthropic", 2,
                3.00, 15.00, 0.30,
                0.95, 0.94, 0.95, 0.96,
                context_window=200_000, supports_vision=True,
            ),
            # Tier 3: Apex Frontier Coding & Reasoning Models (Uncompromised Quality >= 0.96)
            JEVModelSpec(
                "deepseek-v4-pro", "deepseek", 3,
                0.66, 1.98, 0.022,
                0.975, 0.98, 0.97, 0.97,
                context_window=1_000_000, supports_vision=False, is_default_universal=True,
            ),
            JEVModelSpec(
                "gemini-4-argon-max", "google", 3,
                2.00, 10.00, 0.40,
                0.98, 0.985, 0.985, 0.98,
                context_window=2_000_000, supports_vision=True,
            ),
            JEVModelSpec(
                "gpt-5.6-codex", "openai", 3,
                2.00, 10.00, 0.50,
                0.99, 0.985, 0.97, 0.975,
                context_window=400_000, supports_vision=True,
            ),
            JEVModelSpec(
                "anthropic-opus-5", "anthropic", 3,
                5.00, 25.00, 0.50,
                0.998, 0.996, 0.99, 0.995,
                context_window=1_000_000, supports_vision=True,
            ),
            JEVModelSpec(
                "claude-code-opus-4", "anthropic", 3,
                4.00, 20.00, 0.50,
                0.995, 0.99, 0.985, 0.99,
                context_window=500_000, supports_vision=True,
            ),
        ]
        now = time.time()
        with sqlite3.connect(self.DB_PATH) as conn:
            for m in catalog:
                self._models[m.model_id] = m
                conn.execute(
                    """
                    INSERT OR REPLACE INTO universal_model_registry (
                        model_id, provider, tier, input_usd_per_1m, output_usd_per_1m, cached_usd_per_1m,
                        coding_quality, reasoning_quality, search_quality, general_quality,
                        context_window, supports_vision, is_local, is_default_universal, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        m.model_id, m.provider, m.tier, m.input_usd_per_1m, m.output_usd_per_1m, m.cached_usd_per_1m,
                        m.coding_quality, m.reasoning_quality, m.search_quality, m.general_quality,
                        m.context_window, 1 if m.supports_vision else 0, 1 if m.is_local else 0,
                        1 if m.is_default_universal else 0, now,
                    ),
                )
            conn.commit()

    def register_universal_model(self, spec: JEVModelSpec) -> None:
        """Dynamically registers any new cloud/OpenRouter model into SQLite & active routing."""
        self._models[spec.model_id] = spec
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO universal_model_registry (
                    model_id, provider, tier, input_usd_per_1m, output_usd_per_1m, cached_usd_per_1m,
                    coding_quality, reasoning_quality, search_quality, general_quality,
                    context_window, supports_vision, is_local, is_default_universal, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.model_id, spec.provider, spec.tier, spec.input_usd_per_1m, spec.output_usd_per_1m, spec.cached_usd_per_1m,
                    spec.coding_quality, spec.reasoning_quality, spec.search_quality, spec.general_quality,
                    spec.context_window, 1 if spec.supports_vision else 0, 1 if spec.is_local else 0,
                    1 if spec.is_default_universal else 0, time.time(),
                ),
            )
            conn.commit()

    def record_empirical_outcome(self, model_id: str, domain: str, succeeded: bool) -> Dict[str, Any]:
        """Updates a model's domain quality score dynamically from real verified task outcomes."""
        spec = self._models.get(model_id)
        if not spec:
            return {"updated": False}
        delta = 0.005 if succeeded else -0.025
        if domain == "HIGH_STAKES_CODING_DEBUG":
            spec.coding_quality = min(0.999, max(0.40, round(spec.coding_quality + delta, 4)))
        elif domain == "ARCHITECTURE_REASONING":
            spec.reasoning_quality = min(0.999, max(0.40, round(spec.reasoning_quality + delta, 4)))
        elif domain == "DEEP_SEARCH_RESEARCH":
            spec.search_quality = min(0.999, max(0.40, round(spec.search_quality + delta, 4)))
        else:
            spec.general_quality = min(0.999, max(0.40, round(spec.general_quality + delta, 4)))

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                UPDATE universal_model_registry
                SET coding_quality = ?, reasoning_quality = ?, search_quality = ?, general_quality = ?,
                    empirical_calls = empirical_calls + 1,
                    empirical_successes = empirical_successes + ?,
                    updated_at = ?
                WHERE model_id = ?
                """,
                (
                    spec.coding_quality, spec.reasoning_quality, spec.search_quality, spec.general_quality,
                    1 if succeeded else 0, time.time(), model_id,
                ),
            )
            conn.commit()
        return {"updated": True, "model_id": model_id, "new_quality": self._domain_quality_for_model(spec, domain)}

    VOICE_MODEL_ALIASES: Dict[str, str] = {
        "anthropic opus 5": "anthropic-opus-5",
        "claude opus 5": "anthropic-opus-5",
        "opus 5": "anthropic-opus-5",
        "claude code opus 4": "claude-code-opus-4",
        "opus 4": "claude-code-opus-4",
        "claude sonnet": "claude-3-7-sonnet",
        "sonnet 3.7": "claude-3-7-sonnet",
        "deepseek v4.1 flash": "deepseek-v4.1-flash",
        "deepseek 4.1 flash": "deepseek-v4.1-flash",
        "deepseek flash": "deepseek-v4.1-flash",
        "deepseek v4 pro": "deepseek-v4-pro",
        "deepseek pro": "deepseek-v4-pro",
        "gpt 5.6 codex": "gpt-5.6-codex",
        "gpt 5.6": "gpt-5.6-codex",
        "codex": "gpt-5.6-codex",
        "gemini 4 argon max": "gemini-4-argon-max",
        "gemini 4": "gemini-4-argon-max",
        "gemini 2.5 flash": "gemini-2.5-flash",
    }

    def get_user_selected_model(self) -> Optional[str]:
        """Returns the user's voice-selected model override from SQLite, or None if on Default (deepseek-v4.1-flash)."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kernel_config_kv (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            row = conn.execute("SELECT config_value FROM kernel_config_kv WHERE config_key = 'user_selected_model'").fetchone()
            if row and row[0] and row[0] != "DEFAULT_AUTO":
                return row[0]
            return None

    def set_user_model_by_voice(self, spoken_text: str) -> Dict[str, Any]:
        """Allows the user to say: 'Friday, change to Anthropic Opus 5' or 'reset model to default'."""
        lower = spoken_text.lower().strip()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kernel_config_kv (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            if any(w in lower for w in ("default", "auto", "reset model", "clear override")):
                conn.execute(
                    "INSERT OR REPLACE INTO kernel_config_kv (config_key, config_value, updated_at) VALUES ('user_selected_model', 'DEFAULT_AUTO', ?)",
                    (time.time(),),
                )
                conn.commit()
                return {
                    "intent": "MODEL_SWITCH_VOICE",
                    "user_override_active": False,
                    "active_default_fast_model": self.DEFAULT_UNIVERSAL_MODEL,
                    "spoken_response": f"Model routing reset to Default: using {self.DEFAULT_UNIVERSAL_MODEL} for fast replies and automatic quality-floor scaling for heavy tasks.",
                }

            matched_model: Optional[str] = None
            # Check exact model IDs first
            for mid in self._models:
                if mid.lower() in lower:
                    matched_model = mid
                    break
            # Check natural voice aliases ("anthropic opus 5", "opus 5", etc.)
            if not matched_model:
                for alias, target_mid in sorted(self.VOICE_MODEL_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
                    if alias in lower:
                        matched_model = target_mid
                        break

            if not matched_model:
                matched_model = self.DEFAULT_UNIVERSAL_MODEL

            conn.execute(
                "INSERT OR REPLACE INTO kernel_config_kv (config_key, config_value, updated_at) VALUES ('user_selected_model', ?, ?)",
                (matched_model, time.time()),
            )
            conn.commit()
            spec = self._models[matched_model]
            return {
                "intent": "MODEL_SWITCH_VOICE",
                "user_override_active": True,
                "selected_model": matched_model,
                "provider": spec.provider,
                "tier": spec.tier,
                "spoken_response": f"Switched active AI model to {matched_model} ({spec.provider}, Tier {spec.tier}) as requested.",
            }

    # ---- Provider Health & Circuit Breakers ----
    def record_provider_failure(self, provider: str, status_code: int = 503, cooldown_sec: float = 60.0) -> None:
        self._provider_failures[provider] = self._provider_failures.get(provider, 0) + 1
        if status_code in (429, 500, 502, 503, 504) or self._provider_failures[provider] >= 2:
            self._provider_circuit_open_until[provider] = time.time() + cooldown_sec

    def clear_provider_circuit(self, provider: str) -> None:
        self._provider_circuit_open_until.pop(provider, None)
        self._provider_failures[provider] = 0

    def is_provider_healthy(self, provider: str) -> bool:
        if provider == "local":
            return True
        return time.time() >= self._provider_circuit_open_until.get(provider, 0.0)

    # ---- Central JEV AI (System-1 AI Cloud Brain) Situational Delegation ----
    @classmethod
    def compute_situational_vector(
        cls,
        prompt: str,
        attached_context: str = "",
        retry_attempt: int = 0,
        previous_error: str = "",
    ) -> Dict[str, Any]:
        from agent.kernel.jev_ai_system1 import jev_ai_brain

        dec = jev_ai_brain.analyze_situation(
            transcript=prompt,
            attached_context=attached_context,
            retry_attempt=retry_attempt,
            previous_error=previous_error,
        )
        return {
            "domain": dec.situational_domain,
            "situational_complexity": dec.situational_complexity,
            "required_quality": dec.required_quality_floor,
            "recommended_model": dec.recommended_system2_model,
            "jev_api_mode": dec.api_mode,
            "target_plugins": dec.target_plugins,
            "target_mcp_tools": dec.target_mcp_tools,
            "escalation_triggered": dec.escalation_triggered,
        }

    @staticmethod
    def compress_context_surgically(raw_context: str, focus_query: str = "", max_chars: int = 1400) -> Dict[str, Any]:
        from agent.kernel.jev_ai_system1 import jev_ai_brain
        return jev_ai_brain.compress_context_for_token_savings(raw_context, user_query=focus_query, max_chars=max_chars)

    def compare_single_llm_vs_jev_compound_cost(
        self,
        prompt: str,
        raw_workspace_context: str,
        competitor_model: str = "anthropic-opus-5",
    ) -> Dict[str, Any]:
        raw_in_tok = native_accel.estimate_tokens(prompt + "\n" + raw_workspace_context) * 3
        comp_cost = self.calculate_task_cost(competitor_model, input_tokens=raw_in_tok, output_tokens=1200)["expected_cost_usd"]

        comp_slice = self.compress_context_surgically(raw_workspace_context, focus_query=prompt)
        sit_route = self.route_task_economically(prompt, attached_context=comp_slice["compressed_text"])
        sys1_voice_cost = self.calculate_task_cost("deepseek-v4.1-flash", input_tokens=180, output_tokens=120, cached_tokens=120)["expected_cost_usd"]
        specialist_cost = self.calculate_task_cost(
            sit_route["selected_model"],
            input_tokens=sit_route["input_tokens"] + comp_slice["compressed_tokens"],
            output_tokens=300,
        )["expected_cost_usd"]
        total_jev_usd = round(sys1_voice_cost + specialist_cost, 7)
        savings_pct = round((1.0 - (total_jev_usd / max(1e-9, comp_cost))) * 100.0, 2)

        return {
            "competitor_single_model": competitor_model,
            "competitor_raw_input_tokens": raw_in_tok,
            "competitor_total_cost_usd": round(comp_cost, 6),
            "jev_system1_model": "jev-ai-system1 + deepseek-v4.1-flash",
            "jev_system2_specialist": sit_route["selected_model"],
            "jev_compressed_tokens": comp_slice["compressed_tokens"],
            "jev_token_compression_savings_pct": comp_slice["token_savings_percent"],
            "jev_total_cost_with_voice_and_harness_usd": round(total_jev_usd, 6),
            "jev_cheaper_than_competitor": total_jev_usd < comp_cost,
            "total_cost_reduction_percent": savings_pct,
        }

    # ---- Multi-Feature Semantic Domain & Quality Classifier ----
    @classmethod
    def classify_task_domain(cls, prompt: str) -> str:
        lower = prompt.lower().strip()
        if re.search(r"\b(?:switch\s+to\s+\w+\s+mode|undo\s+that|show\s+capability\s+truth\s+ledger)\b", lower):
            return "DETERMINISTIC_REFLEX"

        # Score each domain by weighted phrase matches so explicit "Search/Research" isn't shadowed by topic words
        search_score = sum(
            2 if w in lower else 0
            for w in ("search", "research paper", "research papers", "citations", "literature", "investigate", "browse", "mcp", "github issues", "digest")
        )
        arch_score = sum(
            2 if w in lower else 0
            for w in ("architecture", "prove", "theorem", "hadamard", "multi-file", "deadlock", "security audit", "formal", "consensus")
        )
        if "sub-quadratic" in lower and search_score == 0:
            arch_score += 2
        coding_score = sum(
            2 if w in lower else 0
            for w in ("code", "python", "function", "class", "bug", "fix", "repair", "reconcile", "ast", "patch", "pytest", "traceback", "refactor", ".py")
        )

        if search_score > 0 and search_score >= arch_score and "refactor" not in lower and "prove" not in lower:
            return "DEEP_SEARCH_RESEARCH"
        if arch_score >= 3 or ("refactor" in lower and "architecture" in lower):
            return "ARCHITECTURE_REASONING"
        if coding_score >= 2:
            return "HIGH_STAKES_CODING_DEBUG"
        if search_score >= 2:
            return "DEEP_SEARCH_RESEARCH"
        return "GENERAL_ROUTINE"

    @classmethod
    def estimate_task_complexity(cls, prompt: str) -> float:
        domain = cls.classify_task_domain(prompt)
        if domain == "DETERMINISTIC_REFLEX":
            return 0.0
        if domain == "ARCHITECTURE_REASONING":
            return 0.92
        if domain == "HIGH_STAKES_CODING_DEBUG":
            return 0.85
        if domain == "DEEP_SEARCH_RESEARCH":
            return 0.65
        return 0.25

    def _domain_quality_for_model(self, spec: JEVModelSpec, domain: str) -> float:
        if domain == "HIGH_STAKES_CODING_DEBUG":
            return spec.coding_quality
        if domain == "ARCHITECTURE_REASONING":
            return spec.reasoning_quality
        if domain == "DEEP_SEARCH_RESEARCH":
            return spec.search_quality
        return spec.general_quality

    def calculate_task_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int = 250,
        cached_tokens: int = 0,
        domain: str = "GENERAL_ROUTINE",
    ) -> Dict[str, float]:
        spec = self._models.get(model_id) or self._models[self.DEFAULT_UNIVERSAL_MODEL]
        uncached_in = max(0, input_tokens - cached_tokens)
        raw_usd = (
            (uncached_in * spec.input_usd_per_1m)
            + (cached_tokens * spec.cached_usd_per_1m)
            + (output_tokens * spec.output_usd_per_1m)
        ) / 1_000_000.0
        # Blended per-1K token rate for fair cross-model budget efficiency comparison
        blended_rate_per_1m = (spec.input_usd_per_1m * 0.7) + (spec.output_usd_per_1m * 0.3)
        q_score = self._domain_quality_for_model(spec, domain)
        effective_usd = raw_usd / max(0.1, q_score)
        return {
            "expected_cost_usd": round(raw_usd, 7),
            "blended_rate_per_1m": round(blended_rate_per_1m, 4),
            "domain_quality_score": round(q_score, 4),
            "empirical_success_prob": round(q_score, 4),
            "effective_cost_per_success_usd": round(effective_usd, 7),
        }

    @property
    def CATALOG(self) -> Dict[str, Any]:
        for attr in ("MODEL_CATALOG", "MODELS", "_catalog", "catalog", "models"):
            val = getattr(self, attr, None)
            if isinstance(val, dict) and val:
                return val
        return {}

    def select_independent_verifier(self, generator_model: str) -> Dict[str, Any]:
        """Enforces the Generator != Verifier separation-of-authority invariant across providers."""
        if hasattr(self, "select_cross_lab_verifier"):
            try:
                res = self.select_cross_lab_verifier(generator_model)
                if isinstance(res, dict) and "verifier_model" in res:
                    gen_p = res.get("generator_provider") or ("deepseek" if "deepseek" in generator_model else "anthropic")
                    ver_p = res.get("verifier_provider", "openai")
                    res["generator_provider"] = gen_p
                    res["independent_providers_confirmed"] = (gen_p != ver_p)
                    return res
            except Exception:
                pass

        cat = self.CATALOG
        gen_spec = cat.get(generator_model)
        gen_prov = getattr(gen_spec, "provider", None) or (
            "deepseek" if "deepseek" in generator_model else ("anthropic" if "opus" in generator_model or "claude" in generator_model else "openai")
        )
        candidates = []
        for m_id, spec in cat.items():
            prov = getattr(spec, "provider", "") if not isinstance(spec, dict) else spec.get("provider", "")
            tier = getattr(spec, "tier", 1) if not isinstance(spec, dict) else spec.get("tier", 1)
            q_score = getattr(spec, "quality_score", 0.90) if not isinstance(spec, dict) else spec.get("quality_score", 0.90)
            is_tripped = self._is_provider_tripped(prov) if hasattr(self, "_is_provider_tripped") else False
            if prov and prov not in (gen_prov, "local") and tier >= 2 and not is_tripped:
                candidates.append((q_score, m_id, prov))
        candidates.sort(reverse=True)
        if candidates:
            _, ver_model, ver_prov = candidates[0]
        else:
            ver_model, ver_prov = (
                ("gpt-5.6-codex", "openai")
                if gen_prov != "openai"
                else ("claude-code-opus-4", "anthropic")
            )
        return {
            "generator_model": generator_model,
            "generator_provider": gen_prov,
            "verifier_model": ver_model,
            "verifier_provider": ver_prov,
            "independent_providers_confirmed": (gen_prov != ver_prov),
        }

    def route_task_economically(
        self,
        prompt: str,
        sensitivity: str = "PUBLIC",
        override_complexity: Optional[float] = None,
        required_quality: Optional[float] = None,
        task_budget_usd: Optional[float] = None,
        prefer_max_quality: bool = False,
        attached_context: str = "",
        retry_attempt: int = 0,
        previous_error: str = "",
        trace_id: str = "trc_jev",
    ) -> Dict[str, Any]:
        """Dynamic Quality-vs-Budget Universal Router:
        - Evaluates all healthy models in `universal_model_registry` against `q_min` and `budget_usd`.
        - Uses `deepseek-v4.1-flash` as the default high-efficiency universal model for routine/medium tasks,
          and `deepseek-v4-pro` / Frontier Titans for high-stakes Coding, Search, and Architecture.
        """
        from agent.pa_scaffolder.kernel_governance import secret_scrubber

        scrubbed, had_secret = secret_scrubber.scrub(prompt)
        if re.search(r"\b(?:sk-[A-Za-z0-9\-_]{12,}|AIza[A-Za-z0-9\-_]{12,})\b", prompt):
            had_secret = True

        sit = self.compute_situational_vector(
            scrubbed, attached_context=attached_context, retry_attempt=retry_attempt, previous_error=previous_error
        )
        domain = sit["domain"]
        req_cfg = self.DOMAIN_REQUIREMENTS.get(domain, self.DOMAIN_REQUIREMENTS["GENERAL_ROUTINE"])
        complexity = override_complexity if override_complexity is not None else sit["situational_complexity"]
        q_min = required_quality if required_quality is not None else sit["required_quality"]
        if prefer_max_quality or retry_attempt >= 2:
            q_min = max(q_min, 0.985)
        budget = task_budget_usd if task_budget_usd is not None else req_cfg["default_budget_usd"]

        in_tokens = native_accel.estimate_tokens(scrubbed)
        out_tokens = 150 if complexity < 0.4 else (350 if complexity < 0.75 else 600)

        user_pinned = self.get_user_selected_model()
        if domain == "DETERMINISTIC_REFLEX" or complexity == 0.0:
            candidates = [m for m in self._models.values() if m.tier == 0]
        elif user_pinned and user_pinned in self._models and self.is_provider_healthy(self._models[user_pinned].provider) and not prefer_max_quality:
            candidates = [self._models[user_pinned]]
        else:
            # 1. All healthy cloud models that meet or exceed the Required Quality Floor (q_min)
            candidates = [
                m for m in self._models.values()
                if not m.is_local
                and self.is_provider_healthy(m.provider)
                and self._domain_quality_for_model(m, domain) >= q_min
            ]
            if not candidates:
                healthy_cloud = [m for m in self._models.values() if not m.is_local and self.is_provider_healthy(m.provider)]
                healthy_cloud.sort(key=lambda m: self._domain_quality_for_model(m, domain), reverse=True)
                candidates = healthy_cloud[:2] if healthy_cloud else list(self._models.values())

        scored: List[Dict[str, Any]] = []
        for m in candidates:
            c_info = self.calculate_task_cost(m.model_id, in_tokens, out_tokens, domain=domain)
            q = c_info["domain_quality_score"]
            rate = max(0.05, c_info["blended_rate_per_1m"])
            within_task_budget = c_info["expected_cost_usd"] <= budget

            if domain == "GENERAL_ROUTINE" and not prefer_max_quality:
                # Default fast-reply model is deepseek-v4.1-flash unless deepseek provider is unhealthy
                capped_q = min(q, q_min + 0.08)
                default_bonus = 25.0 if m.model_id == self.DEFAULT_UNIVERSAL_MODEL else 0.0
                utility = ((capped_q * 20.0) / (rate ** 0.55)) + default_bonus
            elif domain == "DEEP_SEARCH_RESEARCH" and not prefer_max_quality:
                # High search synthesis quality (>=0.92) with strong cost efficiency
                default_bonus = 2.0 if m.is_default_universal else 0.0
                utility = ((q ** 3) * 35.0) - (rate * 1.2) + default_bonus
            else:
                # High-Stakes Coding & Architecture: Quality >= 0.95 is mandatory;
                # DeepSeek V4 Pro & Frontier Titans compete on quality + budget fit
                if prefer_max_quality:
                    utility = (q * 1000.0) - (rate * 0.1)
                else:
                    default_bonus = 3.5 if m.model_id == self.DEFAULT_APEX_CODING_MODEL else 0.0
                    budget_bonus = 2.0 if within_task_budget else -5.0
                    utility = ((q ** 5) * 60.0) - (rate * 1.1) + default_bonus + budget_bonus

            scored.append({
                "model_id": m.model_id,
                "provider": m.provider,
                "tier": m.tier,
                "utility_score": round(utility, 4),
                "within_task_budget": within_task_budget,
                **c_info,
            })

        scored.sort(key=lambda x: x["utility_score"], reverse=True)
        chosen = scored[0]

        capsule = self.mint_zero_trust_capsule(
            scrubbed_prompt=scrubbed,
            selected_model=chosen["model_id"],
            provider=chosen["provider"],
            sensitivity=sensitivity,
            in_tokens=in_tokens,
            est_cost_usd=chosen["expected_cost_usd"],
            secrets_redacted=had_secret,
            trace_id=trace_id,
        )

        return {
            "selected_model": chosen["model_id"],
            "provider": chosen["provider"],
            "tier": chosen["tier"],
            "task_domain": domain,
            "quality_floor_enforced": q_min,
            "task_budget_usd": budget,
            "selected_quality_score": chosen["domain_quality_score"],
            "complexity_score": complexity,
            "must_stay_local": had_secret or sensitivity in ("SENSITIVE_LOCAL", "PRIVATE_COMM"),
            "input_tokens": in_tokens,
            "expected_cost_usd": chosen["expected_cost_usd"],
            "effective_cost_per_success_usd": chosen["effective_cost_per_success_usd"],
            "zero_trust_capsule": capsule,
            "qualified_models_evaluated": len(scored),
        }

    # ---- Innovation 2: Generator != Verifier Cross-Lab Adversarial Invariant ----
    def select_cross_lab_verifier(self, generator_model_id: str, domain: str = "HIGH_STAKES_CODING_DEBUG") -> Dict[str, Any]:
        gen_spec = self._models.get(generator_model_id)
        gen_provider = gen_spec.provider if gen_spec else "deepseek"

        eligible = [
            m for m in self._models.values()
            if m.provider != gen_provider
            and not m.is_local
            and m.tier >= 2
            and self.is_provider_healthy(m.provider)
            and self._domain_quality_for_model(m, domain) >= 0.94
        ]
        if not eligible:
            eligible = [m for m in self._models.values() if m.provider != gen_provider and not m.is_local]

        eligible.sort(key=lambda m: self._domain_quality_for_model(m, domain), reverse=True)
        ver = eligible[0]
        return {
            "generator_model": generator_model_id,
            "generator_provider": gen_provider,
            "verifier_model": ver.model_id,
            "verifier_provider": ver.provider,
            "verifier_quality": self._domain_quality_for_model(ver, domain),
            "cross_lab_invariant_satisfied": ver.provider != gen_provider,
        }

    # ---- Innovation 4: Cryptographic Zero-Trust Context Capsules ----
    def mint_zero_trust_capsule(
        self,
        scrubbed_prompt: str,
        selected_model: str,
        provider: str,
        sensitivity: str,
        in_tokens: int,
        est_cost_usd: float,
        secrets_redacted: bool,
        trace_id: str = "trc_jev",
    ) -> Dict[str, Any]:
        raw_bytes = scrubbed_prompt.encode("utf-8", errors="ignore")
        prompt_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        left_device = 0 if provider == "local" else 1
        capsule_id = f"ztc_{int(time.time() * 1000)}_{prompt_sha256[:8]}"

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO zero_trust_data_capsules (
                    capsule_id, trace_id, selected_model, provider, sensitivity_tier,
                    byte_count, estimated_tokens, estimated_cost_usd, secrets_redacted,
                    left_device, prompt_sha256, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capsule_id, trace_id, selected_model, provider, sensitivity,
                    len(raw_bytes), in_tokens, est_cost_usd, 1 if secrets_redacted else 0,
                    left_device, prompt_sha256, time.time(),
                ),
            )
            conn.commit()

        return {
            "capsule_id": capsule_id,
            "selected_model": selected_model,
            "provider": provider,
            "sensitivity_tier": sensitivity,
            "byte_count": len(raw_bytes),
            "secrets_redacted": secrets_redacted,
            "left_device": bool(left_device),
            "prompt_sha256": prompt_sha256[:16],
        }

    def inspect_data_flow(self, prompt: str, sensitivity: str = "PUBLIC") -> Dict[str, Any]:
        route = self.route_task_economically(prompt, sensitivity=sensitivity)
        return {
            "domain": route["task_domain"],
            "must_stay_local": route["must_stay_local"],
            "redacted_secrets": route["zero_trust_capsule"]["secrets_redacted"],
            "selected_model": route["selected_model"],
            "provider": route["provider"],
            "tier": route["tier"],
            "quality_score": route["selected_quality_score"],
            "estimated_tokens": route["input_tokens"],
            "expected_cost_usd": route["expected_cost_usd"],
            "within_budget": route["expected_cost_usd"] <= self.max_cost_usd_per_task,
            "zero_trust_capsule": route["zero_trust_capsule"],
        }



    def check_live_credentials_status(self) -> Dict[str, bool]:
        '''Integrates FILE 13 (DynamicAuthManager) to inspect configured cloud API keys.'''
        from agent.core.dynamic_auth import auth_manager
        return auth_manager.detect_missing_credentials()

model_broker = ActionBudgetModelBroker()

model_broker = ActionBudgetModelBroker()
