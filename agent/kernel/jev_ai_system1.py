from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.native import native_accel


@dataclass
class JEVPrimitiveResult:
    question_id: str
    primitive_type: str
    value: Any
    probabilities: Dict[str, float]
    confidence: float


@dataclass
class JEVSystemOneDecision:
    request_id: str
    model_version: str
    api_mode: str
    google_live_connected: bool
    primitives: Dict[str, JEVPrimitiveResult]
    situational_domain: str
    situational_complexity: float
    required_quality_floor: float
    recommended_system2_model: str
    emotional_state: str
    fatigue_or_frustration_score: float
    alarm_triggered: bool
    alarm_spec: Dict[str, Any]
    recommended_namespaces: List[str]
    target_plugins: List[str]
    target_mcp_tools: List[str]
    raw_context_tokens: int
    compressed_context_tokens: int
    tokens_saved: int
    token_savings_percent: float
    compressed_context: str
    jev_input_cost_usd: float
    escalation_triggered: bool
    jev_api_latency_ms: float
    remote_calibrated: bool = False
    selected_model_cost_per_1m_usd: float = 0.0
    selected_model_quality: float = 0.0


class TypeSafeJEVSystemOneBrain:
    """Central System-1 Decision Engine: Jev by TypeSafe AI (jev-1.13.0).

    Zero hardcoded LLM names: dynamically queries `universal_model_registry`
    (and syncs with OpenRouter's live model catalog) to select System-2 models
    purely by:
      1. Jev RLCD Confidence Score
      2. Task Difficulty / Situational Complexity
      3. Model Domain Output Quality & Empirical Win Rate
      4. Model Cost per 1M Tokens (Input + Output blended rate)
    """

    DB_PATH = Path("workspace/kernel_governance.db")
    DEFAULT_API_URL = "https://api.typesafe.ai/v1/systemone"
    OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
    MODEL_VERSION = "jev-1.13.0"
    INPUT_USD_PER_1M = 0.042
    OUTPUT_USD_PER_1M = 0.0

    STOPWORDS: Set[str] = {
        "the", "and", "for", "with", "that", "this", "from", "into", "your", "have",
        "are", "was", "were", "will", "would", "could", "should", "about", "what",
    }

    def __init__(self) -> None:
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jev_cloud_api_config (
                    provider_name TEXT PRIMARY KEY,
                    api_key TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jev_system1_telemetry (
                    request_id TEXT PRIMARY KEY,
                    model_version TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    api_mode TEXT NOT NULL,
                    situational_domain TEXT NOT NULL,
                    recommended_model TEXT NOT NULL,
                    mean_confidence REAL NOT NULL,
                    tokens_saved INTEGER NOT NULL,
                    jev_cost_usd REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jev_alarms_and_timers (
                    alarm_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    alarm_type TEXT NOT NULL,
                    trigger_spec TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
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

    def sync_openrouter_directory_to_sqlite(self, timeout_sec: float = 4.0) -> Dict[str, Any]:
        """Fetches the live OpenRouter model directory (200+ models) and populates
        `universal_model_registry` with real per-million token costs and estimated domain quality.
        """
        req = urllib.request.Request(
            self.OPENROUTER_MODELS_URL,
            headers={"User-Agent": "ORYN-ModelDirectorySync/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"synced": False, "error": str(exc), "models_ingested": 0}

        raw_models = payload.get("data", [])
        now = time.time()
        ingested = 0

        with sqlite3.connect(self.DB_PATH) as conn:
            for item in raw_models:
                mid = str(item.get("id", "")).strip()
                if not mid:
                    continue
                pricing = item.get("pricing") or {}
                try:
                    in_per_tok = float(pricing.get("prompt", 0.0))
                    out_per_tok = float(pricing.get("completion", 0.0))
                except (TypeError, ValueError):
                    continue

                in_1m = round(max(0.0, in_per_tok * 1_000_000.0), 4)
                out_1m = round(max(0.0, out_per_tok * 1_000_000.0), 4)
                cached_1m = round(in_1m * 0.25, 4)
                ctx_len = int(item.get("context_length") or 128000)
                arch = item.get("architecture") or {}
                modality = str(arch.get("modality", "")).lower()
                has_vision = 1 if ("image" in modality or "multimodal" in modality) else 0
                provider = mid.split("/")[0] if "/" in mid else "openrouter"

                # Estimate initial prior quality from capability tier & context before empirical updates
                blended = (in_1m * 0.7) + (out_1m * 0.3)
                if blended >= 3.0:
                    tier, base_q = 3, 0.96
                elif blended >= 0.5:
                    tier, base_q = 2, 0.92
                else:
                    tier, base_q = 1, 0.86

                low_id = mid.lower()
                code_bonus = 0.03 if any(k in low_id for k in ("coder", "codex", "sonnet", "opus", "deepseek", "gpt-5")) else 0.0
                reason_bonus = 0.03 if any(k in low_id for k in ("r1", "think", "pro", "opus", "o3", "gpt-5", "gemini")) else 0.0

                conn.execute(
                    """
                    INSERT OR IGNORE INTO universal_model_registry (
                        model_id, provider, tier, input_usd_per_1m, output_usd_per_1m, cached_usd_per_1m,
                        coding_quality, reasoning_quality, search_quality, general_quality,
                        context_window, supports_vision, is_local, is_default_universal, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    """,
                    (
                        mid,
                        provider,
                        tier,
                        in_1m,
                        out_1m,
                        cached_1m,
                        min(0.995, round(base_q + code_bonus, 4)),
                        min(0.995, round(base_q + reason_bonus, 4)),
                        min(0.995, round(base_q + 0.01, 4)),
                        min(0.995, round(base_q, 4)),
                        ctx_len,
                        has_vision,
                        now,
                    ),
                )
                ingested += 1
            conn.commit()

        return {"synced": True, "models_ingested": ingested}

    def _load_model_directory(self) -> List[Dict[str, Any]]:
        """Loads all models from `universal_model_registry`. If empty, triggers model_broker seeding."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("SELECT * FROM universal_model_registry").fetchall()]

        if not rows:
            try:
                from agent.kernel.model_broker import model_broker

                model_broker._seed_universal_registry()
                with sqlite3.connect(self.DB_PATH) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = [dict(r) for r in conn.execute("SELECT * FROM universal_model_registry").fetchall()]
            except Exception:
                pass
        return rows

    def select_model_from_directory(
        self,
        transcript: str,
        domain: str,
        task_difficulty: float,
        jev_confidence: float,
        require_vision: bool = False,
        escalated: bool = False,
    ) -> Dict[str, Any]:
        """Dynamically selects the optimal model from the SQLite model directory
        using (jev_confidence, task_difficulty, output_quality, cost_per_1m) with zero hardcoded model IDs.
        """
        directory = self._load_model_directory()
        if not directory:
            return {
                "model_id": "dynamic:unseeded_registry",
                "blended_cost_per_1m": 0.0,
                "domain_quality": 0.0,
                "required_quality_floor": 0.85,
            }

        # 1. If task difficulty is 0.0 (pure local reflex) and Jev confidence is high, select local tier-0 model
        if task_difficulty <= 0.05 and jev_confidence >= 0.75 and not escalated:
            local_models = [m for m in directory if int(m.get("is_local", 0)) == 1 or int(m.get("tier", 1)) == 0]
            if local_models:
                chosen_local = local_models[0]
                return {
                    "model_id": str(chosen_local["model_id"]),
                    "blended_cost_per_1m": 0.0,
                    "domain_quality": float(chosen_local.get("general_quality", 0.99)),
                    "required_quality_floor": 0.99,
                }

        # 2. Compute dynamic Required Quality Floor from Task Difficulty and Jev Confidence
        # Lower Jev confidence (uncertainty) or higher difficulty increases required LLM output quality
        uncertainty_penalty = max(0.0, (0.85 - jev_confidence) * 0.12)
        base_floor = 0.82 + (task_difficulty * 0.14) + uncertainty_penalty
        if escalated:
            base_floor = max(base_floor, 0.98)
        required_quality = round(min(0.99, max(0.80, base_floor)), 4)

        quality_col = {
            "HIGH_STAKES_CODING_DEBUG": "coding_quality",
            "ARCHITECTURE_REASONING": "reasoning_quality",
            "DEEP_SEARCH_RESEARCH": "search_quality",
        }.get(domain, "general_quality")

        cloud_candidates: List[Dict[str, Any]] = []
        for m in directory:
            if int(m.get("is_local", 0)) == 1:
                continue
            if require_vision and int(m.get("supports_vision", 0)) == 0:
                continue

            prior_q = float(m.get(quality_col, m.get("general_quality", 0.85)))
            calls = int(m.get("empirical_calls", 0))
            succ = int(m.get("empirical_successes", 0))
            emp_q = (succ / calls) if calls >= 3 else prior_q
            effective_q = round((prior_q * 0.75) + (emp_q * 0.25), 4)

            in_1m = float(m.get("input_usd_per_1m", 0.5))
            out_1m = float(m.get("output_usd_per_1m", 1.5))
            blended_cost = round((in_1m * 0.7) + (out_1m * 0.3), 4)

            cloud_candidates.append(
                {
                    **m,
                    "effective_quality": effective_q,
                    "blended_cost_per_1m": blended_cost,
                }
            )

        if not cloud_candidates:
            cloud_candidates = [
                {
                    **m,
                    "effective_quality": float(m.get(quality_col, 0.85)),
                    "blended_cost_per_1m": float(m.get("input_usd_per_1m", 0.0)),
                }
                for m in directory
            ]

        qualified = [m for m in cloud_candidates if m["effective_quality"] >= required_quality]
        if not qualified:
            cloud_candidates.sort(key=lambda x: x["effective_quality"], reverse=True)
            qualified = cloud_candidates[:3]

        # 3. Score qualified models by Quality, Task Difficulty, and Cost per 1M Tokens
        # High difficulty weights quality exponentially; low difficulty strongly rewards low $/1M cost
        quality_exponent = 2.0 + (task_difficulty * 6.0)
        cost_sensitivity = max(0.15, 1.35 - task_difficulty)

        for cand in qualified:
            q_val = cand["effective_quality"]
            c_val = max(0.02, cand["blended_cost_per_1m"])
            pareto_score = ((q_val ** quality_exponent) * 100.0) / (c_val ** cost_sensitivity)
            cand["pareto_score"] = round(pareto_score, 4)

        qualified.sort(key=lambda x: x["pareto_score"], reverse=True)
        best = qualified[0]

        return {
            "model_id": str(best["model_id"]),
            "blended_cost_per_1m": float(best["blended_cost_per_1m"]),
            "domain_quality": float(best["effective_quality"]),
            "required_quality_floor": required_quality,
        }

    def configure_api_key(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        provider_name: str = "typesafe_jev",
    ) -> Dict[str, Any]:
        url = base_url or self.DEFAULT_API_URL
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jev_cloud_api_config (provider_name, api_key, base_url, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (provider_name, api_key.strip(), url, time.time()),
            )
            conn.commit()
        return {
            "provider": provider_name,
            "model_version": self.MODEL_VERSION,
            "configured": bool(api_key.strip()),
            "base_url": url,
        }

    def get_api_credentials(self, provider_name: str = "typesafe_jev") -> Dict[str, str]:
        env_key = (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY") or "").strip()
        env_url = os.environ.get("TYPESAFE_API_URL", self.DEFAULT_API_URL).strip()
        if env_key:
            return {"api_key": env_key, "base_url": env_url, "source": "environment"}
        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute(
                "SELECT api_key, base_url FROM jev_cloud_api_config WHERE provider_name IN ('typesafe_jev', 'jev_ai', ?) LIMIT 1",
                (provider_name,),
            ).fetchone()
            if row and row[0]:
                return {"api_key": row[0], "base_url": row[1], "source": "sqlite_vault"}
        return {"api_key": "", "base_url": env_url, "source": "unconfigured"}

    @classmethod
    def _extract_features(cls, text: str) -> Dict[str, float]:
        clean = re.sub(r"[^a-z0-9_#]+", " ", text.lower()).strip()
        feats: Dict[str, float] = {}
        tokens = [t for t in clean.split() if len(t) > 2 and t not in cls.STOPWORDS]
        for tok in tokens:
            feats[f"w:{tok}"] = feats.get(f"w:{tok}", 0.0) + 2.0
            for suf in (
                "ication", "ization", "ating", "ition", "ment", "ness",
                "ying", "ing", "tion", "ed", "ly", "es", "s",
            ):
                if len(tok) - len(suf) >= 3 and tok.endswith(suf):
                    stem = tok[: -len(suf)]
                    feats[f"st:{stem}"] = feats.get(f"st:{stem}", 0.0) + 1.6
                    break
            if len(tok) >= 4:
                for i in range(len(tok) - 2):
                    tri = tok[i : i + 3]
                    feats[f"g:{tri}"] = feats.get(f"g:{tri}", 0.0) + 0.35
        return feats

    @classmethod
    def compute_semantic_alignment(cls, text_a: str, text_b: str) -> float:
        if not text_a.strip() or not text_b.strip():
            return 0.0
        fa = cls._extract_features(text_a)
        fb = cls._extract_features(text_b)
        if not fa or not fb:
            return 0.0
        dot = sum(w * fb.get(k, 0.0) for k, w in fa.items())
        norm_a = math.sqrt(sum(w * w for w in fa.values()))
        norm_b = math.sqrt(sum(w * w for w in fb.values()))
        cos = dot / max(1e-9, norm_a * norm_b)
        la, lb = text_a.lower(), text_b.lower()
        phrase_bonus = 0.25 if (lb in la or la in lb) else 0.0
        return round(min(1.0, cos + phrase_bonus), 4)

    @staticmethod
    def compute_rlcd_confidence(probs: Dict[str, float]) -> float:
        if not probs:
            return 0.0
        vals = sorted(probs.values(), reverse=True)
        top_p = vals[0]
        second_p = vals[1] if len(vals) > 1 else 0.0
        margin = top_p - second_p
        return round(min(0.999, max(0.01, (top_p * 0.65) + (margin * 0.35))), 4)

    @staticmethod
    def _normalize_questions_for_typesafe_api(questions: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        api_questions: Dict[str, Dict[str, Any]] = {}
        for q_id, q_spec in questions.items():
            q_type = q_spec.get("type", "noul").lower()
            instructions = str(q_spec.get("instructions") or f"Evaluate {q_id}")
            if q_type == "choice":
                if "criteria" in q_spec and isinstance(q_spec["criteria"], dict):
                    criteria = q_spec["criteria"]
                else:
                    opts = list(q_spec.get("options", ["other"]))[:255]
                    descs = q_spec.get("option_descriptions", {})
                    criteria = {opt: descs.get(opt, opt) for opt in opts}
                api_questions[q_id] = {"type": "choice", "instructions": instructions, "criteria": criteria}
            elif q_type == "score":
                levels = q_spec.get("criteria") or [str(x) for x in q_spec.get("levels", [1, 2, 3, 4, 5])]
                api_questions[q_id] = {"type": "score", "instructions": instructions, "criteria": list(levels)[:10]}
            else:
                api_questions[q_id] = {"type": "noul", "instructions": instructions}
        return api_questions

    @fault_recorder.guard(subsystem="kernel.jev_ai_system1")
    def evaluate_primitives(
        self,
        state: str | Dict[str, Any] | List[str],
        questions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, JEVPrimitiveResult]:
        state_str = json.dumps(state, default=str) if not isinstance(state, str) else state
        creds = self.get_api_credentials("typesafe_jev")

        if creds["api_key"]:
            try:
                api_q = self._normalize_questions_for_typesafe_api(questions)
                payload = json.dumps(
                    {"model": self.MODEL_VERSION, "state": state, "questions": api_q}
                ).encode("utf-8")
                req = urllib.request.Request(
                    creds["base_url"],
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {creds['api_key']}",
                        "Content-Type": "application/json",
                        "User-Agent": "ORYN-JEV/1.13.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    answers = resp_data.get("answers", {})
                    cloud_results: Dict[str, JEVPrimitiveResult] = {}
                    for q_id, q_ans in answers.items():
                        q_type = q_ans.get("type", questions.get(q_id, {}).get("type", "noul")).lower()
                        if q_type == "choice":
                            probs = {str(k): float(v) for k, v in q_ans.get("probabilities", {}).items()}
                            cloud_results[q_id] = JEVPrimitiveResult(
                                question_id=q_id,
                                primitive_type="choice",
                                value=q_ans.get("choice", "other"),
                                probabilities=probs,
                                confidence=float(q_ans.get("confidence", self.compute_rlcd_confidence(probs))),
                            )
                        elif q_type == "score":
                            probs = {str(k): float(v) for k, v in q_ans.get("probabilities", {}).items()}
                            cloud_results[q_id] = JEVPrimitiveResult(
                                question_id=q_id,
                                primitive_type="score",
                                value=float(q_ans.get("score", 0.5)),
                                probabilities=probs,
                                confidence=float(q_ans.get("confidence", self.compute_rlcd_confidence(probs))),
                            )
                        else:
                            p_yes = float(q_ans.get("noul", 0.5))
                            probs = {"true": round(p_yes, 4), "false": round(1.0 - p_yes, 4)}
                            cloud_results[q_id] = JEVPrimitiveResult(
                                question_id=q_id,
                                primitive_type="noul",
                                value=bool(p_yes > 0.5),
                                probabilities=probs,
                                confidence=float(q_ans.get("confidence", self.compute_rlcd_confidence(probs))),
                            )
                    if cloud_results:
                        return cloud_results
            except Exception:
                pass

        lower_state = state_str.lower()
        results: Dict[str, JEVPrimitiveResult] = {}

        for q_id, q_spec in questions.items():
            q_type = q_spec.get("type", "noul").lower()

            if q_type == "noul":
                pos_sigs = [s.lower() for s in q_spec.get("affirmative_signals", [])]
                neg_sigs = [s.lower() for s in q_spec.get("negative_signals", [])]
                hits_pos = sum(1 for s in pos_sigs if s in lower_state)
                hits_neg = sum(1 for s in neg_sigs if s in lower_state)
                instr = str(q_spec.get("instructions", ""))
                sem_align = self.compute_semantic_alignment(state_str, instr) if instr else 0.0

                if hits_pos > 0 and hits_neg == 0:
                    p_true = min(0.985, 0.78 + (hits_pos * 0.08) + (sem_align * 0.1))
                elif hits_pos > hits_neg:
                    p_true = 0.68 + (sem_align * 0.15)
                elif hits_neg > 0:
                    p_true = 0.04
                elif sem_align > 0.48:
                    p_true = min(0.92, 0.55 + (sem_align * 0.35))
                else:
                    p_true = float(q_spec.get("prior_true", 0.08))

                p_true = round(p_true, 4)
                probs = {"true": p_true, "false": round(1.0 - p_true, 4)}
                conf = self.compute_rlcd_confidence(probs)
                results[q_id] = JEVPrimitiveResult(
                    question_id=q_id,
                    primitive_type="noul",
                    value=(p_true > 0.5),
                    probabilities=probs,
                    confidence=conf,
                )

            elif q_type == "choice":
                criteria = q_spec.get("criteria")
                if isinstance(criteria, dict):
                    options = list(criteria.keys())
                    opt_descriptions = {k: str(v or k) for k, v in criteria.items()}
                else:
                    options = list(q_spec.get("options", ["other"]))
                    opt_descriptions = dict(q_spec.get("option_descriptions", {}))
                if "other" not in options:
                    options.append("other")

                opt_sigs: Dict[str, List[str]] = q_spec.get("option_signals", {})
                raw_weights: Dict[str, float] = {opt: 0.08 for opt in options}
                default_opt = q_spec.get("default_option", options[0])
                raw_weights[default_opt] = raw_weights.get(default_opt, 0.08) + 0.25

                for opt in options:
                    if opt == "other":
                        continue
                    for sig in opt_sigs.get(opt, []):
                        sig_low = sig.lower()
                        if sig_low in lower_state:
                            raw_weights[opt] += 2.4
                        else:
                            align = self.compute_semantic_alignment(lower_state, sig_low)
                            if align > 0.25:
                                raw_weights[opt] += align * 1.8
                    desc = opt_descriptions.get(opt, opt.replace("_", " ").replace(".", " "))
                    desc_align = self.compute_semantic_alignment(lower_state, desc)
                    raw_weights[opt] += desc_align * 2.0

                total_w = sum(raw_weights.values()) or 1.0
                probs = {k: round(v / total_w, 4) for k, v in raw_weights.items()}
                best_opt = max(probs.items(), key=lambda kv: kv[1])[0]
                conf = self.compute_rlcd_confidence(probs)
                results[q_id] = JEVPrimitiveResult(
                    question_id=q_id,
                    primitive_type="choice",
                    value=best_opt,
                    probabilities=probs,
                    confidence=conf,
                )

            elif q_type == "score":
                raw_levels = q_spec.get("levels") or [1, 2, 3, 4, 5]
                levels: List[int] = [int(i) if str(i).isdigit() else idx + 1 for idx, i in enumerate(raw_levels)]
                high_sigs = [s.lower() for s in q_spec.get("high_signals", [])]
                mid_sigs = [s.lower() for s in q_spec.get("mid_signals", [])]
                h_hits = sum(1 for s in high_sigs if s in lower_state)
                m_hits = sum(1 for s in mid_sigs if s in lower_state)

                if h_hits >= 2:
                    dist = {str(levels[-1]): 0.76, str(levels[-2]): 0.18, str(levels[0]): 0.06}
                elif h_hits == 1:
                    dist = {str(levels[-1]): 0.45, str(levels[-2]): 0.42, str(levels[0]): 0.13}
                elif m_hits >= 1:
                    mid_l = str(levels[len(levels) // 2])
                    dist = {mid_l: 0.72, str(levels[0]): 0.18, str(levels[-1]): 0.10}
                else:
                    dist = {str(levels[0]): 0.78, str(levels[min(1, len(levels) - 1)]): 0.17, str(levels[-1]): 0.05}

                expected_val = sum(float(k) * v for k, v in dist.items())
                norm_score = round(expected_val / max(levels), 4)
                conf = self.compute_rlcd_confidence(dist)
                results[q_id] = JEVPrimitiveResult(
                    question_id=q_id,
                    primitive_type="score",
                    value=norm_score,
                    probabilities=dist,
                    confidence=conf,
                )

        return results

    def select_screen_or_dom_action(
        self,
        user_goal: str,
        ui_elements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        elem_ids: List[str] = []
        elem_descriptions: Dict[str, str] = {}
        elem_signals: Dict[str, List[str]] = {}
        goal_low = user_goal.lower()
        wants_click_btn = any(
            w in goal_low for w in ("click", "press", "tap", "button", "submit", "complete", "pay", "finish")
        )
        wants_input_type = any(
            w in goal_low for w in ("type", "enter text", "fill", "input", "write in")
        )

        for i, el in enumerate(ui_elements[:254]):
            eid = str(el.get("ref_id") or el.get("selector") or el.get("id") or f"#el_{i}")
            elem_ids.append(eid)
            tag = str(el.get("tag") or el.get("role") or "").lower()
            label = str(el.get("label") or el.get("name") or "")
            role = str(el.get("role", ""))
            role_hint = (
                "clickable button submit action"
                if tag in ("button", "a", "link", "menuitem")
                else ("text input field" if tag in ("input", "textarea", "textbox", "edit") else role)
            )
            elem_descriptions[eid] = f"{label} {eid} {tag} {role_hint}".strip()
            words = [w.lower() for w in re.findall(r"[a-zA-Z0-9_]{3,}", f"{label} {eid}")]
            if tag in ("button", "link") and wants_click_btn:
                words.extend(["click", "button"])
            elif tag in ("input", "textbox", "textarea") and wants_input_type:
                words.extend(["type", "input"])
            elem_signals[eid] = words

        q_batch = {
            "ui_operation": {
                "type": "choice",
                "options": ["click", "type_text", "scroll_down", "open_app_intent", "press_enter", "done", "other"],
                "default_option": "click",
                "option_signals": {
                    "click": ["click", "press", "tap", "complete", "submit", "pay", "button", "checkout", "finish"],
                    "type_text": ["type", "enter text", "input", "write", "search", "fill"],
                    "scroll_down": ["scroll", "down", "more", "next page"],
                    "open_app_intent": ["open app", "launch", "start app", "reels", "instagram", "spotify"],
                },
            },
            "target_element": {
                "type": "choice",
                "options": elem_ids + ["other"],
                "default_option": elem_ids[0] if elem_ids else "other",
                "option_signals": elem_signals,
                "option_descriptions": elem_descriptions,
            },
            "action_is_safe": {
                "type": "noul",
                "affirmative_signals": ["checkout", "click", "search", "open", "submit", "inspect", "complete", "finish"],
                "negative_signals": ["delete all", "format disk", "rm -rf", "wire transfer"],
                "prior_true": 0.92,
            },
            "needs_small_llm_for_typing": {
                "type": "noul",
                "affirmative_signals": ["write an essay", "draft a reply", "compose", "summarize"],
            },
        }

        prims = self.evaluate_primitives(user_goal, q_batch)
        in_tok = native_accel.estimate_tokens(user_goal + json.dumps(ui_elements[:50]))
        cost_usd = round((in_tok * self.INPUT_USD_PER_1M) / 1_000_000.0, 7)

        return {
            "model": self.MODEL_VERSION,
            "selected_operation": prims["ui_operation"].value,
            "operation_confidence": prims["ui_operation"].confidence,
            "target_element_selector": prims["target_element"].value,
            "target_confidence": prims["target_element"].confidence,
            "action_is_safe": prims["action_is_safe"].value,
            "needs_llm_text_generation": prims["needs_small_llm_for_typing"].value,
            "jev_decision_cost_usd": max(0.000001, cost_usd),
        }

    def moderate_streamer_live_chat_batch(self, comments: List[Dict[str, str]]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        decisions: List[Dict[str, Any]] = []
        counts = {"allow": 0, "highlight_question": 0, "auto_reply_faq": 0, "delete_spam": 0, "timeout_600s": 0}
        total_tokens = 0

        for item in comments:
            user = item.get("user", "viewer")
            msg = item.get("message", "")
            total_tokens += native_accel.estimate_tokens(msg)
            q_mod = {
                "mod_action": {
                    "type": "choice",
                    "options": ["allow", "highlight_question", "auto_reply_faq", "delete_spam", "timeout_600s", "other"],
                    "default_option": "allow",
                    "option_signals": {
                        "timeout_600s": ["idiot", "trash streamer", "hate you", "slur", "kill", "doxx", "raid spam"],
                        "delete_spam": ["free crypto", "click my bio", "http://bit.ly", "buy followers", "win $1000"],
                        "auto_reply_faq": ["what pc specs", "what rank", "what sensitivity", "what IDE", "which model"],
                        "highlight_question": ["how did you", "can you explain", "why does the", "question about"],
                    },
                },
                "toxicity_severity": {
                    "type": "score",
                    "levels": [1, 2, 3, 4, 5],
                    "high_signals": ["idiot", "trash", "slur", "kill", "doxx", "scam", "free crypto"],
                    "mid_signals": ["annoying", "boring", "lag"],
                },
                "is_viewer_question": {
                    "type": "noul",
                    "affirmative_signals": ["?", "how ", "what ", "why ", "can you"],
                },
            }
            res = self.evaluate_primitives(msg, q_mod)
            act = res["mod_action"].value
            counts[act] = counts.get(act, 0) + 1
            decisions.append(
                {
                    "user": user,
                    "message": msg[:80],
                    "mod_action": act,
                    "confidence": res["mod_action"].confidence,
                    "toxicity_score": res["toxicity_severity"].value,
                    "is_question": res["is_viewer_question"].value,
                }
            )

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        jev_cost = round((total_tokens * self.INPUT_USD_PER_1M) / 1_000_000.0, 7)
        return {
            "model": self.MODEL_VERSION,
            "comments_processed": len(comments),
            "action_summary": counts,
            "decisions": decisions,
            "batch_latency_ms": dur_ms,
            "jev_total_cost_usd": max(0.000001, jev_cost),
        }

    def audit_and_filter_memories(
        self,
        query_or_new_fact: str,
        candidate_memories: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        kept: List[Dict[str, Any]] = []
        contradictions: List[Dict[str, Any]] = []
        q_words = set(re.findall(r"[a-zA-Z0-9_]{4,}", query_or_new_fact.lower())) - self.STOPWORDS

        for mem in candidate_memories:
            content = str(mem.get("content") or mem.get("label") or "")
            m_words = set(re.findall(r"[a-zA-Z0-9_]{4,}", content.lower())) - self.STOPWORDS
            overlap = list(q_words.intersection(m_words))
            sem_score = self.compute_semantic_alignment(query_or_new_fact, content)
            neg_a = bool(re.search(r"\b(?:not|no\s+longer|never|none|stopped)\b", query_or_new_fact.lower()))
            neg_b = bool(re.search(r"\b(?:not|no\s+longer|never|none|stopped)\b", content.lower()))
            has_negation_flip = (neg_a != neg_b) and (len(overlap) >= 2 or sem_score >= 0.35)

            q_mem = {
                "is_relevant": {
                    "type": "noul",
                    "affirmative_signals": overlap if (overlap or sem_score >= 0.30) else ["_none_"],
                },
                "is_contradiction": {
                    "type": "noul",
                    "affirmative_signals": overlap if has_negation_flip else ["_none_"],
                },
            }
            prims = self.evaluate_primitives(f"{query_or_new_fact} || {content}", q_mem)
            if prims["is_relevant"].value:
                kept.append({**mem, "jev_relevance_confidence": prims["is_relevant"].confidence})
            if prims["is_contradiction"].value:
                contradictions.append({**mem, "jev_contradiction_confidence": prims["is_contradiction"].confidence})

        return {
            "relevant_memories": kept,
            "contradictions_detected": contradictions,
            "contradiction_count": len(contradictions),
        }

    def recommend_memory_namespaces(self, prompt: str) -> List[str]:
        q_ns = {
            "primary_namespace": {
                "type": "choice",
                "options": [
                    "coding_and_architecture",
                    "research_knowledge",
                    "schedule_and_alarms",
                    "nutrition_and_diet",
                    "health_and_biometrics",
                    "social_and_relationships",
                    "ambitions_and_goals",
                    "financial_and_business",
                    "device_and_environment",
                    "communication_preferences",
                    "education_and_learning",
                    "digital_accounts",
                    "entertainment_and_interests",
                    "travel_and_locations",
                    "other",
                ],
                "default_option": "coding_and_architecture",
                "option_descriptions": {
                    "coding_and_architecture": "python code repository ast bug function class refactor test git",
                    "research_knowledge": "research paper arxiv citation experiment math theorem dataset literature",
                    "schedule_and_alarms": "alarm timer reminder schedule calendar meeting wake up",
                    "nutrition_and_diet": "food diet calories macros protein allergic peanuts groundnuts meal",
                    "health_and_biometrics": "sleep heart rate hrv recovery workout health tracker",
                    "social_and_relationships": "brother karthik rahul family friend whatsapp slack discord message",
                    "ambitions_and_goals": "startup yc goal ambition roadmap milestone career",
                    "financial_and_business": "budget cost invoice billing price payment",
                    "device_and_environment": "mode builder streamer gamer cpu gpu volume light",
                    "communication_preferences": "concise short detailed response style tone",
                },
            }
        }
        res = self.evaluate_primitives(prompt, q_ns)
        chosen = res["primary_namespace"].value
        return [chosen] if chosen != "other" else ["coding_and_architecture"]

    @staticmethod
    def compress_context_for_token_savings(
        raw_context: str,
        user_query: str = "",
        max_chars: int = 1400,
        preserve_full_if_high_entropy: bool = False,
    ) -> Dict[str, Any]:
        raw_tokens = native_accel.estimate_tokens(raw_context)
        if preserve_full_if_high_entropy or len(raw_context) <= max_chars:
            return {
                "compressed_text": raw_context,
                "raw_tokens": raw_tokens,
                "compressed_tokens": raw_tokens,
                "tokens_saved": 0,
                "token_savings_percent": 0.0,
            }

        focus_terms = [w.lower() for w in re.findall(r"[a-zA-Z_]{4,}", user_query)]
        kept: List[str] = []
        for idx, ln in enumerate(raw_context.splitlines()):
            low_ln = ln.lower()
            if (
                any(
                    k in low_ln
                    for k in ("def ", "class ", "import ", "from ", "assert ", "error", "exception", "line ", "<button", "<input", "<a ")
                )
                or any(ft in low_ln for ft in focus_terms)
            ):
                kept.append(f"L{idx+1}: {ln.strip()}")
                if sum(len(x) for x in kept) >= max_chars:
                    break

        compressed = "\n".join(kept) if kept else raw_context[:max_chars]
        comp_tokens = max(1, native_accel.estimate_tokens(compressed))
        saved = max(0, raw_tokens - comp_tokens)
        saved_pct = round(max(0.0, (saved / max(1, raw_tokens)) * 100.0), 1)
        return {
            "compressed_text": compressed,
            "raw_tokens": raw_tokens,
            "compressed_tokens": comp_tokens,
            "tokens_saved": saved,
            "token_savings_percent": saved_pct,
        }

    def analyze_situation(
        self,
        transcript: str,
        attached_context: str = "",
        retry_attempt: int = 0,
        previous_error: str = "",
        google_live_active: bool = False,
    ) -> JEVSystemOneDecision:
        t0 = time.perf_counter()
        creds = self.get_api_credentials("typesafe_jev")
        api_mode = "LIVE_TYPESAFE_JEV_API" if creds["api_key"] else "CALIBRATED_LOCAL_ENGINE"
        comp = self.compress_context_for_token_savings(attached_context, user_query=transcript)
        lower = transcript.lower().strip()
        words = lower.split()

        is_reflex = (
            re.search(r"\b(?:switch\s+to\s+\w+\s+mode|undo\s+that|show\s+capability\s+truth\s+ledger)\b", lower)
            is not None
        )
        is_shallow_factual = (
            len(words) < 15
            and re.match(r"^(?:what\s+is|what's|who\s+is|define|tell\s+me\s+the\s+name|summarize\s+this\s+short)\b", lower)
            is not None
            and not any(w in lower for w in ("bug", "error", "crash", "fix", "why", "race", "deadlock", "refactor", "prove"))
        )

        q_batch = {
            "emotional_state": {
                "type": "choice",
                "options": ["calm_focused", "exhausted_tired", "urgent_critical", "frustrated_stressed", "casual_friendly", "other"],
                "default_option": "calm_focused",
                "option_signals": {
                    "exhausted_tired": ["exhausted", "tired", "sleepy", "drained", "long day"],
                    "urgent_critical": ["urgent", "immediately", "asap", "emergency", "production down", "quick"],
                    "frustrated_stressed": ["wtf", "broken again", "annoying", "frustrated", "stuck"],
                    "casual_friendly": ["bro", "hey", "mate", "awesome", "cool"],
                },
            },
            "fatigue_or_frustration": {
                "type": "score",
                "levels": [1, 2, 3, 4, 5],
                "high_signals": ["exhausted", "tired", "frustrated", "emergency", "looks weird"],
                "mid_signals": ["bro", "busy"],
            },
            "task_difficulty_score": {
                "type": "score",
                "levels": [1, 2, 3, 4, 5],
                "high_signals": [
                    "architecture", "prove", "theorem", "hadamard", "multi-file", "deadlock",
                    "race condition", "reconcile", "refactor", "security audit", "traceback", "bug", "fix",
                ],
                "mid_signals": ["search", "research", "compare", "literature", "citations", "browse", "mcp"],
            },
            "is_alarm_or_timer": {
                "type": "noul",
                "affirmative_signals": ["wake me up", "set an alarm", "set alarm", "timer for", "remind me at", "call alarm"],
            },
            "is_shallow_lookup": {
                "type": "noul",
                "affirmative_signals": ["what is the file extension", "summarize this short", "what is a"] if is_shallow_factual else ["_none_"],
            },
        }

        prims = self.evaluate_primitives(transcript, q_batch)
        alarm_triggered = bool(prims["is_alarm_or_timer"].value)
        alarm_spec: Dict[str, Any] = {}
        if alarm_triggered:
            m_time = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|minutes|mins|hours|hrs|seconds|secs)?)", lower)
            t_spec = m_time.group(1).strip() if m_time else "next_scheduled_slot"
            aid = f"alm_{int(time.time() * 1000)}"
            alarm_spec = {
                "alarm_id": aid,
                "trigger_spec": t_spec,
                "confidence": prims["is_alarm_or_timer"].confidence,
                "status": "ARMED_IN_KERNEL",
            }
            with sqlite3.connect(self.DB_PATH) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO jev_alarms_and_timers (alarm_id, label, alarm_type, trigger_spec, confidence, status, created_at) VALUES (?, ?, 'VOICE_ALARM', ?, ?, 'ARMED', ?)",
                    (aid, transcript[:120], t_spec, prims["is_alarm_or_timer"].confidence, time.time()),
                )
                conn.commit()

        plugins: List[str] = []
        mcp_tools: List[str] = []
        if any(w in lower for w in (".py", "ast", "code", "bug", "fix", "reconcile", "patch", "function", "class", "race condition")):
            plugins.append("plugin.builder")
        if any(w in lower for w in ("mcp", "github", "sqlite", "repository", "audit workspace")):
            plugins.append("plugin.mcp_bridge")
            mcp_tools.append(
                "sqlite.query_metrics"
                if "sqlite" in lower
                else ("filesystem.audit_workspace" if "audit" in lower else "github.analyze_repo_issues")
            )
        if any(w in lower for w in ("whatsapp", "reply to", "message", "schedule", "remind", "alarm", "timer")):
            plugins.append("plugin.messaging_schedule")
        if any(w in lower for w in ("web", "http", "instagram", "reels", "pdf", "book", "chapter")):
            plugins.append("plugin.web_media")
        if any(w in lower for w in ("youtube", "video", "transcript")):
            plugins.append("plugin.youtube")
        if any(w in lower for w in ("remember", "memory", "graph", "allergic", "brother")):
            plugins.append("plugin.life_memory")
        if any(w in lower for w in ("mode", "screen", "iot", "light")):
            plugins.append("plugin.vision_iot_mode")

        causal_signals = (
            "race condition", "same millisecond", "goes negative", "why does", "root cause",
            "intermittent", "memory leak", "deadlock", "state corruption", "prove", "theorem",
            "sub-quadratic", "hadamard", "multi-file", "architecture", "security audit",
            "reconcile", "refactor", "traceback", "exception", "bug", "fix", "repair",
        )
        causal_hits = sum(1 for s in causal_signals if s in lower)
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
            for w in ("code", "python", "function", "class", "bug", "fix", "repair", "reconcile", "ast", "patch", "pytest", "traceback", "refactor", ".py", "race condition", "same millisecond", "goes negative")
        )

        if is_reflex:
            domain = "DETERMINISTIC_REFLEX"
            complexity = 0.0
        elif is_shallow_factual and retry_attempt == 0:
            domain = "GENERAL_ROUTINE"
            complexity = 0.18
        elif search_score > 0 and search_score >= arch_score and "refactor" not in lower and "prove" not in lower:
            domain = "DEEP_SEARCH_RESEARCH"
            complexity = 0.68
        elif arch_score >= 3 or ("refactor" in lower and "architecture" in lower):
            domain = "ARCHITECTURE_REASONING"
            complexity = 0.94
        elif coding_score >= 2 or causal_hits >= 1:
            domain = "HIGH_STAKES_CODING_DEBUG"
            complexity = 0.88
        else:
            domain = "GENERAL_ROUTINE"
            complexity = float(prims["task_difficulty_score"].value) * 0.5

        escalated = retry_attempt > 0 or bool(previous_error)
        if escalated:
            complexity = min(0.99, complexity + 0.25)
            if domain == "GENERAL_ROUTINE":
                domain = "HIGH_STAKES_CODING_DEBUG"

        mean_conf = round(sum(p.confidence for p in prims.values()) / max(1, len(prims)), 4)

        # Dynamic Model Directory Selection (0 Hardcoded Model Strings)
        dir_pick = self.select_model_from_directory(
            transcript=transcript,
            domain=domain,
            task_difficulty=complexity,
            jev_confidence=mean_conf,
            escalated=escalated,
        )
        rec_model = dir_pick["model_id"]
        q_floor = dir_pick["required_quality_floor"]

        rec_namespaces = self.recommend_memory_namespaces(transcript)
        in_tokens = max(1, native_accel.estimate_tokens(transcript) + comp["compressed_tokens"])
        jev_cost = round((in_tokens * self.INPUT_USD_PER_1M) / 1_000_000.0, 8)
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        req_id = f"jev_{int(time.time() * 1000)}_{hashlib.sha256(transcript.encode()).hexdigest()[:6]}"

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jev_system1_telemetry (
                    request_id, model_version, transcript, api_mode, situational_domain,
                    recommended_model, mean_confidence, tokens_saved, jev_cost_usd, latency_ms, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req_id, self.MODEL_VERSION, transcript[:200], api_mode, domain,
                    rec_model, mean_conf, comp["tokens_saved"], jev_cost, dur_ms, time.time(),
                ),
            )
            conn.commit()

        return JEVSystemOneDecision(
            request_id=req_id,
            model_version=self.MODEL_VERSION,
            api_mode=api_mode,
            google_live_connected=google_live_active,
            primitives=prims,
            situational_domain=domain,
            situational_complexity=complexity,
            required_quality_floor=q_floor,
            recommended_system2_model=rec_model,
            emotional_state=prims["emotional_state"].value,
            fatigue_or_frustration_score=prims["fatigue_or_frustration"].value,
            alarm_triggered=alarm_triggered,
            alarm_spec=alarm_spec,
            recommended_namespaces=rec_namespaces,
            target_plugins=plugins or ["plugin.life_memory"],
            target_mcp_tools=mcp_tools,
            raw_context_tokens=comp["raw_tokens"],
            compressed_context_tokens=comp["compressed_tokens"],
            tokens_saved=comp["tokens_saved"],
            token_savings_percent=comp["token_savings_percent"],
            compressed_context=comp["compressed_text"],
            jev_input_cost_usd=jev_cost,
            escalation_triggered=escalated,
            jev_api_latency_ms=dur_ms,
            remote_calibrated=bool(creds["api_key"]),
            selected_model_cost_per_1m_usd=dir_pick["blended_cost_per_1m"],
            selected_model_quality=dir_pick["domain_quality"],
        )

    async def process_google_live_transcription_through_jev_ai(
        self,
        google_live_transcript: str,
        engine: Any,
        attached_context: str = "",
    ) -> Dict[str, Any]:
        s1_decision = self.analyze_situation(
            transcript=google_live_transcript,
            attached_context=attached_context,
            google_live_active=True,
        )
        exec_res = await engine.process_voice_turn(google_live_transcript)
        exec_res["jev_system1_brain"] = {
            "request_id": s1_decision.request_id,
            "model_version": s1_decision.model_version,
            "api_mode": s1_decision.api_mode,
            "google_live_connected": s1_decision.google_live_connected,
            "situational_domain": s1_decision.situational_domain,
            "recommended_system2_model": s1_decision.recommended_system2_model,
            "selected_model_cost_per_1m_usd": s1_decision.selected_model_cost_per_1m_usd,
            "selected_model_quality": s1_decision.selected_model_quality,
            "emotional_state": s1_decision.emotional_state,
            "fatigue_score": s1_decision.fatigue_or_frustration_score,
            "alarm_triggered": s1_decision.alarm_triggered,
            "alarm_spec": s1_decision.alarm_spec,
            "recommended_namespaces": s1_decision.recommended_namespaces,
            "target_plugins": s1_decision.target_plugins,
            "target_mcp_tools": s1_decision.target_mcp_tools,
            "token_savings_percent": s1_decision.token_savings_percent,
            "jev_input_cost_usd": s1_decision.jev_input_cost_usd,
            "jev_api_latency_ms": s1_decision.jev_api_latency_ms,
        }
        return exec_res


JEVSystemOneCloudAPI = TypeSafeJEVSystemOneBrain
jev_ai_brain = TypeSafeJEVSystemOneBrain()
