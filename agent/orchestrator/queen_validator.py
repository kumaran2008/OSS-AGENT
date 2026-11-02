import os
import sys
import ast
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path

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

from agent.memory.federated_ledger import SharedRootLedger, SharedRootLedgerState


@dataclass
class ValidationResult:
    approved: bool
    rejection_reasons: List[str] = field(default_factory=list)
    sanitized_delta: Dict[str, Any] = field(default_factory=dict)


class QueenLedgerValidator:
    """
    Hardware-adaptive gatekeeper for worker scratchpad commits.
    Validates proposed invariants, milestones, and modified files
    before permitting commits into the SharedRootLedger.
    """
    def __init__(self, workspace_root: str, root_ledger: SharedRootLedger):
        self.workspace_root = Path(workspace_root)
        self.root_ledger = root_ledger
        self.tier = detect_hardware_tier()

        # Hard anti-patterns / forbidden words for unverified invariant staging
        self.forbidden_invariant_patterns = [
            r"assume",
            r"probably",
            r"maybe",
            r"might work",
            r"untested",
            r"temporary fix",
            r"TODO",
        ]

    def validate_worker_pr(self, agent_id: str, role: str, worker_delta: Dict[str, Any]) -> ValidationResult:
        rejections: List[str] = []
        current_root: SharedRootLedgerState = self.root_ledger.get_read_only_view()

        # -------------------------------------------------------------
        # 1. Deterministic Validation: Modified Files & Syntax Check
        # -------------------------------------------------------------
        verified_files = []
        for file_path_str in worker_delta.get("files_touched", []):
            target_path = self.workspace_root / file_path_str
            if not target_path.exists():
                rejections.append(f"File claim invalid: '{file_path_str}' does not exist on disk.")
                continue

            # If it is a Python file, run a strict AST syntax check (Zero RAM cost, runs everywhere)
            if file_path_str.endswith(".py"):
                try:
                    with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                        ast.parse(f.read(), filename=file_path_str)
                except SyntaxError as e:
                    rejections.append(f"Syntax validation failed in '{file_path_str}' at line {e.lineno}: {e.msg}")
                    continue

            verified_files.append(file_path_str)

        # -------------------------------------------------------------
        # 2. Invariant Conflict & Quality Verification
        # -------------------------------------------------------------
        sanitized_invariants = []
        for inv in worker_delta.get("candidate_invariants", []):
            inv_lower = inv.lower()

            # Rule A: Invariants must have substance (> 15 chars)
            if len(inv.strip()) < 15:
                rejections.append(f"Invariant too trivial/vague: '{inv}'")
                continue

            # Rule B: Invariants must not contain speculative language
            matched_pattern = next((p for p in self.forbidden_invariant_patterns if p in inv_lower), None)
            if matched_pattern:
                rejections.append(f"Speculative invariant rejected (matches '{matched_pattern}'): '{inv}'")
                continue

            # Rule C: Check for direct contradiction against existing root invariants
            contradicts = False
            for existing in current_root.invariants:
                if self._check_direct_negation(inv_lower, existing.lower()):
                    rejections.append(f"Contradiction detected: '{inv}' contradicts existing root invariant '{existing}'")
                    contradicts = True
                    break

            if not contradicts:
                sanitized_invariants.append(inv)

        # -------------------------------------------------------------
        # 3. Milestone Completion Integrity Check
        # -------------------------------------------------------------
        sanitized_completions = []
        for milestone in worker_delta.get("resolved_milestones", []):
            # A worker cannot resolve a milestone that was never registered in root or scratchpad
            if milestone not in current_root.pending_milestones and milestone not in worker_delta.get("pending_milestones", []):
                # Warning rather than rejection: allow self-declared tasks if role matches
                if role not in ["builder", "tester", "researcher"]:
                    rejections.append(f"Unauthorized milestone completion attempt by {role}: '{milestone}'")
                    continue
            sanitized_completions.append(milestone)

        # -------------------------------------------------------------
        # 4. Final Verdict Determination
        # -------------------------------------------------------------
        is_approved = len(rejections) == 0

        sanitized_delta = {
            "candidate_invariants": sanitized_invariants,
            "resolved_milestones": sanitized_completions,
            "pending_milestones": worker_delta.get("pending_milestones", []),
            "files_touched": verified_files,
            "verified_facts": worker_delta.get("verified_facts", [])
        }

        return ValidationResult(
            approved=is_approved,
            rejection_reasons=rejections,
            sanitized_delta=sanitized_delta
        )

    def review_and_commit(self, agent_id: str, role: str, worker_delta: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Main entry point for Queen Agent: reviews delta, commits if valid,
        or returns actionable diagnostics to the worker.
        """
        result = self.validate_worker_pr(agent_id, role, worker_delta)

        if not result.approved:
            error_report = (
                f"[QUEEN REJECTION] PR from {agent_id} ({role}) failed validation:\n"
                + "\n".join(f"  - {err}" for err in result.rejection_reasons)
            )
            return False, error_report

        # Commit sanitized payload into the root ledger
        self.root_ledger.commit_worker_delta(result.sanitized_delta)
        return True, f"[QUEEN APPROVED] Delta from {agent_id} committed to Root Ledger (Rev {self.root_ledger.get_read_only_view().revision})."

    @staticmethod
    def _check_direct_negation(phrase_a: str, phrase_b: str) -> bool:
        """Lightweight heuristic to catch basic polarity reversals without heavy NLP."""
        negations = ["never", "do not", "don't", "prohibit", "avoid"]
        a_has_neg = any(n in phrase_a for n in negations)
        b_has_neg = any(n in phrase_b for n in negations)

        # If one asserts prohibition and the other does not, check lexical overlap
        if a_has_neg != b_has_neg:
            words_a = set(w for w in phrase_a.split() if len(w) > 4)
            words_b = set(w for w in phrase_b.split() if len(w) > 4)
            common = words_a.intersection(words_b)
            if len(common) >= 2:
                return True
        return False
