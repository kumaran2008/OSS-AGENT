from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from agent.kernel.plugin_host import Action, ActionResult, AuthorizedTaskContext, VerificationResult


class ProofCarryingVerifierJournal:
    """Mints Machine-Readable Proof-Carrying Action Receipts and persists them to SQLite."""

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proof_carrying_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    grant_id TEXT NOT NULL,
                    approval_hash TEXT NOT NULL,
                    expected_postconditions TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    observed_evidence TEXT NOT NULL,
                    provider_receipt TEXT,
                    uncertainty_reason TEXT,
                    compensation_available INTEGER NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.commit()

    def build_and_store_receipt(
        self,
        action: Action,
        context: AuthorizedTaskContext,
        exec_result: ActionResult,
        ver_result: VerificationResult,
    ) -> Dict[str, Any]:
        receipt_id = f"rcpt_{action.action_id}"
        receipt = {
            "receipt_id": receipt_id,
            "trace_id": context.trace_id,
            "action_id": action.action_id,
            "capability_id": action.capability_id,
            "target": action.target,
            "authorization": {
                "grant_id": context.grant_id,
                "policy_rule": context.policy_rule_matched,
                "approval_hash": context.approval_hash,
                "allow_remote_processing": context.allow_remote_processing,
            },
            "expected_postconditions": action.postconditions,
            "status": ver_result.status,
            "verified": ver_result.verified,
            "evidence_type": ver_result.evidence_type,
            "observed_evidence": ver_result.observed_evidence,
            "provider_receipt": exec_result.provider_receipt,
            "uncertainty_reason": ver_result.uncertainty_reason,
            "compensation_available": exec_result.compensation_available,
            "timestamp": time.time(),
        }
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO proof_carrying_receipts (
                    receipt_id, trace_id, action_id, capability_id, target,
                    grant_id, approval_hash, expected_postconditions, verification_status,
                    evidence_type, observed_evidence, provider_receipt, uncertainty_reason,
                    compensation_available, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    context.trace_id,
                    action.action_id,
                    action.capability_id,
                    action.target,
                    context.grant_id,
                    context.approval_hash,
                    json.dumps(action.postconditions),
                    ver_result.status,
                    ver_result.evidence_type,
                    ver_result.observed_evidence,
                    exec_result.provider_receipt,
                    ver_result.uncertainty_reason,
                    1 if exec_result.compensation_available else 0,
                    receipt["timestamp"],
                ),
            )
            conn.commit()
        return receipt


verifier_journal = ProofCarryingVerifierJournal()
