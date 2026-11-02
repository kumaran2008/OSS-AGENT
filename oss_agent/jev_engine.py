from __future__ import annotations
import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass(frozen=True)
class JevChoiceResult:
    selected_choice: str
    confidence: float
    probabilities: Dict[str, float]

@dataclass(frozen=True)
class JevNoulResult:
    probability: float
    verdict: bool

class JevDecisionEngine:
    """TypeSafe Jev System-1 decision interface.
    Handles sub-100ms classification, routing, and binary gating without generative hallucination.
    """

    def __init__(self, api_key: Optional[str] = None, endpoint: str = "https://api.typesafe.ai/v1/decide"):
        self.api_key = api_key
        self.endpoint = endpoint

    def decide_choice(self, state: Dict[str, Any], prompt: str, options: List[str]) -> JevChoiceResult:
        """TypeSafe Jev 'Choice' primitive: selects 1 option from a list with calibrated probabilities."""
        if not options:
            raise ValueError("Choice primitive requires at least one option.")

        if not self.api_key:
            return self._heuristic_choice(state, prompt, options)

        payload = {
            "state": state,
            "question": {"type": "choice", "prompt": prompt, "options": options[:255]}
        }
        try:
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choice", options[0])
                conf = float(data.get("confidence", 0.9))
                probs = data.get("probabilities", {choice: conf})
                return JevChoiceResult(selected_choice=choice, confidence=conf, probabilities=probs)
        except Exception:
            return self._heuristic_choice(state, prompt, options)

    def decide_noul(self, state: Dict[str, Any], statement: str, threshold: float = 0.5) -> JevNoulResult:
        """TypeSafe Jev 'Noul' primitive: evaluates a yes/no statement into a probability (0.0 to 1.0)."""
        if not self.api_key:
            prob = 0.9 if any(k in statement.lower() for k in ["safe", "read", "check"]) else 0.4
            return JevNoulResult(probability=prob, verdict=(prob >= threshold))

        payload = {
            "state": state,
            "question": {"type": "noul", "statement": statement}
        }
        try:
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                prob = float(data.get("probability", 0.5))
                return JevNoulResult(probability=prob, verdict=(prob >= threshold))
        except Exception:
            return JevNoulResult(probability=0.5, verdict=False)

    def _heuristic_choice(self, state: Dict[str, Any], prompt: str, options: List[str]) -> JevChoiceResult:
        text = str(state).lower() + " " + prompt.lower()
        best_opt = options[0]
        max_score = -1
        for opt in options:
            score = sum(1 for word in opt.lower().split() if word in text)
            if score > max_score:
                max_score = score
                best_opt = opt
        return JevChoiceResult(selected_choice=best_opt, confidence=0.85, probabilities={best_opt: 0.85})
