import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

try:
    from agent.hardware.runtime_adapter import detect_hardware_tier, RuntimeTier
except ImportError:
    class RuntimeTier:
        LOW_SPEC_MOBILE = "low_spec_mobile"
        MID_SPEC = "mid_spec"
        HIGH_SPEC = "high_spec"

    def detect_hardware_tier():
        is_android = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ
        return RuntimeTier.LOW_SPEC_MOBILE if is_android else RuntimeTier.MID_SPEC


# Role hierarchy matrix for deterministic conflict resolution
ROLE_HIERARCHY: Dict[str, int] = {
    "queen": 100,
    "reviewer": 80,
    "tester": 60,
    "builder": 40,
    "researcher": 20,
    "worker": 10
}


@dataclass
class ConflictResolutionReport:
    accepted_invariants: List[str] = field(default_factory=list)
    rejected_invariants: List[Tuple[str, str]] = field(default_factory=list)  # (invariant, reason)
    resolved_milestones: List[str] = field(default_factory=list)
    conflicted_milestones: List[Tuple[str, str]] = field(default_factory=list) # (milestone, reason)


class AdaptiveConflictResolver:
    def __init__(self):
        self.tier = detect_hardware_tier()
        self.negation_patterns = [
            (r"\bnever\b", r"\balways\b"),
            (r"\bdo not\b", r"\bmust\b"),
            (r"\bprohibit\b", r"\ballow\b"),
            (r"\bdisallow\b", r"\benable\b"),
            (r"\bdeprecated\b", r"\brequired\b")
        ]

    # -------------------------------------------------------------
    # 1. Milestone Resolution: State Monotonicity & Role Precedence
    # -------------------------------------------------------------
    def resolve_milestone_transition(
        self,
        worker_role: str,
        milestone: str,
        action: str,  # "complete" | "add"
        completed_in_root: List[str],
        pending_in_root: List[str],
        root_milestone_authors: Dict[str, str]
    ) -> Tuple[bool, str]:
        """
        Prevents race conditions where a lower-tier agent revives or alters
        a milestone already closed or owned by a higher-tier agent.
        """
        # Rule A: Monotonic Completion (Once completed, a milestone cannot be reopened without higher rank)
        if milestone in completed_in_root and action == "add":
            prior_role = root_milestone_authors.get(milestone, "worker")
            if ROLE_HIERARCHY.get(worker_role, 0) <= ROLE_HIERARCHY.get(prior_role, 0):
                return False, f"Milestone '{milestone}' was marked completed by higher/equal role '{prior_role}'."

        # Rule B: Duplicate Complete (Idempotent success)
        if milestone in completed_in_root and action == "complete":
            return True, "Already completed in root (Idempotent merge)."

        # Rule C: Completing a milestone that was never pending
        if milestone not in pending_in_root and action == "complete":
            if ROLE_HIERARCHY.get(worker_role, 0) < ROLE_HIERARCHY.get("tester", 60):
                return False, f"Role '{worker_role}' cannot complete unregistered milestone '{milestone}'."

        return True, "Approved"

    # -------------------------------------------------------------
    # 2. Invariant Resolution: Polarity Collision & Overlap Analysis
    # -------------------------------------------------------------
    def detect_invariant_collision(self, candidate: str, existing: str) -> bool:
        """
        Deterministic opposition heuristic.
        Runs with zero RAM overhead on mobile and catches direct philosophical splits.
        """
        cand_lower = candidate.lower()
        exist_lower = existing.lower()

        # Tokenize content words (>3 chars)
        cand_words = set(re.findall(r"\b\w{4,}\b", cand_lower))
        exist_words = set(re.findall(r"\b\w{4,}\b", exist_lower))
        shared = cand_words.intersection(exist_words)

        # Require topical overlap (at least 2 substantial subject words match)
        if len(shared) < 2:
            return False

        # Polarity flip check
        for neg, pos in self.negation_patterns:
            c_has_neg = bool(re.search(neg, cand_lower))
            c_has_pos = bool(re.search(pos, cand_lower))
            e_has_neg = bool(re.search(neg, exist_lower))
            e_has_pos = bool(re.search(pos, exist_lower))

            if (c_has_neg and e_has_pos) or (c_has_pos and e_has_neg):
                return True

        return False

    def arbitrate_invariants(
        self,
        worker_role: str,
        candidates: List[str],
        existing_invariants: List[str],
        invariant_authors: Dict[str, str]
    ) -> Tuple[List[str], List[Tuple[str, str]]]:
        """
        Arbitrates invariants.
        If a collision is detected:
        - Higher rank wins outright.
        - Lower/Equal rank is rejected or held in worker scratchpad.
        """
        accepted = []
        rejected = []

        for cand in candidates:
            collided = False
            for exist in existing_invariants:
                if self.detect_invariant_collision(cand, exist):
                    author_role = invariant_authors.get(exist, "queen")
                    worker_weight = ROLE_HIERARCHY.get(worker_role, 0)
                    existing_weight = ROLE_HIERARCHY.get(author_role, 0)

                    if worker_weight > existing_weight:
                        # Replace prior invariant (Authoritative supersede)
                        accepted.append(cand)
                    else:
                        rejected.append((cand, f"Contradicts invariant established by '{author_role}': '{exist}'"))
                    collided = True
                    break

            if not collided and cand not in existing_invariants:
                accepted.append(cand)

        return accepted, rejected
