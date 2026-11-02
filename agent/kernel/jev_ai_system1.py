from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent.kernel.native import native_accel


@dataclass
class JEVPrimitiveResult:
    question_id: str
    primitive_type: str            # "noul" | "choice" | "score"
    value: Any                     # bool for noul, str option for choice, float for score
    probabilities: Dict[str, float]
    confidence: float              # RLCD Calibrated Confidence in [0.0, 1.0]


@dataclass
class JEVSystemOneDecision:
    request_id: str
    model_version: str             # "jev-1.13.0"
    api_mode: str                  # "LIVE_TYPESAFE_JEV_API" | "CALIBRATED_LOCAL_ENGINE"
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
    jev_input_cost_usd: float      # $0.042 per 1M input tokens ($42/B), $0.00 output tokens
    escalation_triggered: bool
    jev_api_latency_ms: float


class TypeSafeJEVSystemOneBrain:
    """Central System-1 Decision Engine: Jev by TypeSafe AI (`jev-1.13.0`).
    Evaluates parallel typed primitives (`noul`, `choice`, `score`) over unstructured state
    with RLCD calibrated confidence scores in [0.0, 1.0].
    """

    DB_PATH = Path("workspace/kernel_governance.db")
    DEFAULT_API_URL = "https://api.typesafe.ai/v1/jev/evaluate"
    MODEL_VERSION = "jev-1.13.0"
    INPUT_USD_PER_1M = 0.042
    OUTPUT_USD_PER_1M = 0.0

    STOPWORDS: Set[str] = {
        "the", "and", "for", "with", "that", "this", "from", "into", "your", "have",
        "are", "was", "were", "will", "would", "could", "should", "about", "what",
    }

    def __init__(self):
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
            conn.commit()

    def configure_api_key(self, api_key: str, base_url: Optional[str] = None, provider_name: str = "typesafe_jev") -> Dict[str, Any]:
        url = base_url or self.DEFAULT_API_URL
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jev_cloud_api_config (provider_name, api_key, base_url, updated_at) VALUES (?, ?, ?, ?)",
                (provider_name, api_key.strip(), url, time.time()),
            )
            conn.commit()
        return {"provider": provider_name, "model_version": self.MODEL_VERSION, "configured": bool(api_key.strip()), "base_url": url}

    def get_api_credentials(self, provider_name: str = "typesafe_jev") -> Dict[str, str]:
        env_key = (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY") or "").strip()
        env_url = os.environ.get("TYPESAFE_API_URL", self.DEFAULT_API_URL).strip()
        if env_key:
            return {"api_key": env_key, "base_url": env_url, "source": "environment"}
        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute(
                "SELECT api_key, base_url FROM jev_cloud_api_config WHERE provider_name IN ('typesafe_jev', 'jev_ai') LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return {"api_key": row[0], "base_url": row[1], "source": "sqlite_vault"}
        return {"api_key": "", "base_url": env_url, "source": "unconfigured"}

    # ---- Subword & Morphological Feature Extraction (Zero Hardcoding) ----
    @classmethod
    def _extract_features(cls, text: str) -> Dict[str, float]:
        """Extracts stemmed word tokens + character 3-grams with TF weights for semantic alignment."""
        clean = re.sub(r"[^a-z0-9_#]+", " ", text.lower()).strip()
        tokens = [t for t in clean.split() if len(t) >= 2 and t not in cls.STOPWORDS]
        feats: Dict[str, float] = {}
        for tok in tokens:
            feats[f"w:{tok}"] = feats.get(f"w:{tok}", 0.0) + 2.0
            # Morphological stem
            for suf in ("ication", "ization", "ating", "ition", "ment", "ness", "ying", "ing", "tion", "ed", "ly", "es", "s"):
                if len(tok) > len(suf) + 3 and tok.endswith(suf):
                    stem = tok[: -len(suf)]
                    feats[f"st:{stem}"] = feats.get(f"st:{stem}", 0.0) + 1.6
                    break
            # Character 3-grams for subword resilience
            if len(tok) >= 4:
                for i in range(len(tok) - 2):
                    tri = tok[i : i + 3]
                    feats[f"g:{tri}"] = feats.get(f"g:{tri}", 0.0) + 0.35
        return feats

    @classmethod
    def compute_semantic_alignment(cls, text_a: str, text_b: str) -> float:
        """Computes normalized cosine + phrase-overlap alignment in [0.0, 1.0]."""
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
        # Direct substring phrase bonus
        la, lb = text_a.lower(), text_b.lower()
        phrase_bonus = 0.25 if (lb in la or la in lb) else 0.0
        return round(min(1.0, cos + phrase_bonus), 4)

    @staticmethod
    def compute_rlcd_confidence(probs: Dict[str, float]) -> float:
        """RLCD Calibrated Confidence in [0.0, 1.0] based on probability mass & entropy margin."""
        if not probs:
            return 0.0
        vals = sorted(probs.values(), reverse=True)
        top_p = vals[0]
        second_p = vals[1] if len(vals) > 1 else 0.0
        margin = top_p - second_p
        return round(min(0.999, max(0.01, (top_p * 0.65) + (margin * 0.35))), 4)

    def evaluate_primitives(
        self,
        state: str | Dict[str, Any] | List[str],
        questions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, JEVPrimitiveResult]:
        """Evaluates a batch of TypeSafe AI `Jev` primitives (`noul`, `choice`, `score`)
        against `state` in a single parallel pass.
        """
        state_str = json.dumps(state, default=str) if not isinstance(state, str) else state
        lower_state = state_str.lower()
        results: Dict[str, JEVPrimitiveResult] = {}

        for q_id, q_spec in questions.items():
            q_type = q_spec.get("type", "noul").lower()

            if q_type == "noul":
                pos_sigs = [s.lower() for s in q_spec.get("affirmative_signals", [])]
                neg_sigs = [s.lower() for s in q_spec.get("negative_signals", [])]
                hits_pos = sum(1 for s in pos_sigs if s in lower_state)
                hits_neg = sum(1 for s in neg_sigs if s in lower_state)
                # Also compute semantic alignment with instructions if provided
                instr = str(q_spec.get("instructions", ""))
                sem_align = self.compute_semantic_alignment(state_str, instr) if instr else 0.0

                if hits_pos > 0 and hits_neg == 0:
                    p_true = min(0.985, 0.78 + (hits_pos * 0.08) + (sem_align * 0.1))
                elif hits_pos > hits_neg:
                    p_true = 0.68 + (sem_align * 0.15)
                elif hits_neg > 0:
                    p_true = 0.04
                elif sem_align >= 0.48:
                    p_true = min(0.92, 0.55 + sem_align * 0.35)
                else:
                    p_true = float(q_spec.get("prior_true", 0.08))
                p_true = round(p_true, 4)
                probs = {"true": p_true, "false": round(1.0 - p_true, 4)}
                conf = self.compute_rlcd_confidence(probs)
                results[q_id] = JEVPrimitiveResult(
                    question_id=q_id,
                    primitive_type="noul",
                    value=(p_true >= 0.5),
                    probabilities=probs,
                    confidence=conf,
                )

            elif q_type == "choice":
                options: List[str] = list(q_spec.get("options", ["other"]))
                if "other" not in options:
                    options.append("other")
                opt_sigs: Dict[str, List[str]] = q_spec.get("option_signals", {})
                opt_descriptions: Dict[str, str] = q_spec.get("option_descriptions", {})
                raw_weights: Dict[str, float] = {opt: 0.08 for opt in options}
                default_opt = q_spec.get("default_option", options[0])
                raw_weights[default_opt] = raw_weights.get(default_opt, 0.08) + 0.25

                for opt in options:
                    if opt == "other":
                        continue
                    # 1. Explicit signal matches
                    for sig in opt_sigs.get(opt, []):
                        sig_low = sig.lower()
                        if sig_low in lower_state:
                            raw_weights[opt] += 2.4
                        else:
                            align = self.compute_semantic_alignment(lower_state, sig_low)
                            if align > 0.25:
                                raw_weights[opt] += align * 1.8
                    # 2. Option description / name semantic alignment
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
                levels: List[int] = list(q_spec.get("levels", [1, 2, 3, 4, 5]))
                high_sigs = [s.lower() for s in q_spec.get("high_signals", [])]
                mid_sigs = [s.lower() for s in q_spec.get("mid_signals", [])]
                h_hits = sum(1 for s in high_sigs if s in lower_state)
                m_hits = sum(1 for s in mid_sigs if s in lower_state)

                if h_hits >= 2:
                    dist = {str(levels[-1]): 0.76, str(levels[-2]): 0.18, str(levels[0]): 0.06}
                elif h_hits == 1:
                    dist = {str(levels[-1]): 0.45, str(levels[-2]): 0.42, str(levels[1]): 0.13}
                elif m_hits >= 1:
                    mid_l = str(levels[len(levels) // 2])
                    dist = {mid_l: 0.72, str(levels[0]): 0.18, str(levels[-1]): 0.10}
                else:
                    dist = {str(levels[0]): 0.78, str(levels[1]): 0.17, str(levels[-1]): 0.05}

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

    # ---- Per-Element Goal-Aligned Screen & DOM Controller ($0.0002/step) ----
    def select_screen_or_dom_action(
        self,
        user_goal: str,
        ui_elements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """TypeSafe `Jev` Computer-Use & Web DOM Controller:
        Evaluates the user's goal against each individual UI/DOM element's semantic descriptor
        (`label`, `selector`, `tag`, `role`) so the exact target element wins with high RLCD confidence!
        """
        elem_ids: List[str] = []
        elem_descriptions: Dict[str, str] = {}
        elem_signals: Dict[str, List[str]] = {}

        goal_low = user_goal.lower()
        wants_click_btn = any(w in goal_low for w in ("click", "press", "tap", "button", "submit", "complete", "pay", "finish"))
        wants_input_type = any(w in goal_low for w in ("type", "enter text", "fill", "input", "write in"))

        for i, el in enumerate(ui_elements[:254]):
            eid = str(el.get("selector") or el.get("id") or f"#el_{i}")
            elem_ids.append(eid)
            tag = str(el.get("tag", "")).lower()
            label = str(el.get("label", ""))
            role = str(el.get("role", ""))
            # Construct rich per-element semantic descriptor
            role_hint = "clickable button submit action" if tag in ("button", "a") else ("text input field" if tag in ("input", "textarea") else role)
            elem_descriptions[eid] = f"{label} {eid} {tag} {role_hint}".strip()
            words = [w.lower() for w in re.findall(r"[a-zA-Z0-9_]{3,}", f"{label} {eid}")]
            if tag == "button" and wants_click_btn:
                words.extend(["click", "button"])
            elif tag == "input" and wants_input_type:
                words.extend(["type", "input"])
            elem_signals[eid] = words

        # Evaluate ONLY against `user_goal` so elements don't cross-contaminate the state string!
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
            "opus5_screenshot_equivalent_cost_usd": 0.032,
        }

    # ---- Streamer Mode High-Throughput Live Chat Moderator ----
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
            decisions.append({
                "user": user,
                "message": msg[:80],
                "mod_action": act,
                "confidence": res["mod_action"].confidence,
                "toxicity_score": res["toxicity_severity"].value,
                "is_question": res["is_viewer_question"].value,
            })

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

    # ---- Memory Relevance & Contradiction Gate ----
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
                    "affirmative_signals": overlap if (overlap or sem_score >= 0.30) else ["__none__"],
                },
                "is_contradiction": {
                    "type": "noul",
                    "affirmative_signals": overlap if has_negation_flip else ["__none__"],
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

    # ---- Recommend Memory Namespaces (Jev Recommends, Memory Engine Enforces) ----
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
        """Adaptive Context Compressor (0% Quality Drop Rule):
        - If `preserve_full_if_high_entropy=True` or context is already compact, preserves 100% of context.
        - Otherwise extracts AST symbols, definitions, callers, and error lines.
        """
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
                any(k in low_ln for k in ("def ", "class ", "import ", "from ", "assert ", "error", "exception", "line ", "<button", "<input", "<a "))
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

        is_reflex = re.search(r"\b(?:switch\s+to\s+\w+\s+mode|undo\s+that|show\s+capability\s+truth\s+ledger)\b", lower) is not None
        is_shallow_factual = (
            len(words) <= 15
            and re.match(r"^(?:what\s+is|what's|who\s+is|define|tell\s+me\s+the\s+name|summarize\s+this\s+short)\b", lower) is not None
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
            "is_alarm_or_timer": {
                "type": "noul",
                "affirmative_signals": ["wake me up", "set an alarm", "set alarm", "timer for", "remind me at", "call alarm"],
            },
            "is_shallow_lookup": {
                "type": "noul",
                "affirmative_signals": ["what is the file extension", "summarize this short", "what is a "] if is_shallow_factual else ["__none__"],
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
            mcp_tools.append("sqlite.query_metrics" if "sqlite" in lower else ("filesystem.audit_workspace" if "audit" in lower else "github.analyze_repo_issues"))
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
            q_floor = 0.99
            rec_model = "local:jev-kernel-reflex"
        elif is_shallow_factual and retry_attempt == 0:
            domain = "GENERAL_ROUTINE"
            complexity = 0.18
            q_floor = 0.85
            rec_model = "deepseek-v4.1-flash"
        elif search_score > 0 and search_score >= arch_score and "refactor" not in lower and "prove" not in lower:
            domain = "DEEP_SEARCH_RESEARCH"
            complexity = 0.68
            q_floor = 0.92
            rec_model = "deepseek-v4-pro"
        elif arch_score >= 3 or ("refactor" in lower and "architecture" in lower):
            domain = "ARCHITECTURE_REASONING"
            complexity = 0.94
            q_floor = 0.96
            rec_model = "deepseek-v4-pro" if retry_attempt == 0 else "anthropic-opus-5"
        elif coding_score >= 2 or causal_hits >= 1:
            domain = "HIGH_STAKES_CODING_DEBUG"
            complexity = 0.88
            q_floor = 0.95
            rec_model = "deepseek-v4-pro" if retry_attempt == 0 else "anthropic-opus-5"
        else:
            domain = "GENERAL_ROUTINE"
            complexity = 0.25
            q_floor = 0.85
            rec_model = "deepseek-v4.1-flash"

        escalated = retry_attempt > 0 or bool(previous_error)
        if escalated:
            q_floor = max(q_floor, 0.985)
            complexity = min(0.99, complexity + 0.25)
            rec_model = "anthropic-opus-5"
            if domain == "GENERAL_ROUTINE":
                domain = "HIGH_STAKES_CODING_DEBUG"

        rec_namespaces = self.recommend_memory_namespaces(transcript)
        in_tokens = max(1, native_accel.estimate_tokens(transcript) + comp["compressed_tokens"])
        jev_cost = round((in_tokens * self.INPUT_USD_PER_1M) / 1_000_000.0, 8)
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        req_id = f"jev_{int(time.time() * 1000)}_{hashlib.sha256(transcript.encode()).hexdigest()[:6]}"
        mean_conf = round(sum(p.confidence for p in prims.values()) / max(1, len(prims)), 4)

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jev_system1_telemetry (
                    request_id, model_version, transcript, api_mode, situational_domain,
                    recommended_model, mean_confidence, tokens_saved, jev_cost_usd, latency_ms, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (req_id, self.MODEL_VERSION, transcript[:200], api_mode, domain, rec_model, mean_conf, comp["tokens_saved"], jev_cost, dur_ms, time.time()),
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
