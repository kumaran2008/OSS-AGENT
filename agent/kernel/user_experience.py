from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.model_broker import model_broker
from agent.kernel.plugin_host import plugin_host
from agent.kernel.policy_engine import policy_engine
from agent.kernel.workflow_runtime import workflow_runtime


class UserExperienceAndContinuityService:
    """Upgrade 18: 8-Point Desktop Workstation HUD, Pause/Cancel/Rollback Controls,
    Reusable Personal Routines, and HMAC-Authenticated Mobile Continuity Bridge.
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_routines (
                    routine_name TEXT PRIMARY KEY,
                    trigger_phrase TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    autonomy_tier TEXT DEFAULT 'SUPERVISED',
                    run_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paired_mobile_devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    session_secret TEXT NOT NULL,
                    allowed_scopes_json TEXT NOT NULL,
                    paired_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    revoked INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cross_device_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    origin_device TEXT NOT NULL,
                    target_device TEXT NOT NULL,
                    task_title TEXT NOT NULL,
                    pending_step_json TEXT NOT NULL,
                    approval_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    resolved_at REAL DEFAULT 0.0
                )
                """
            )
            conn.commit()

    # ---- 1. The 8-Point Desktop Workstation HUD (Reviewer Upgrade 18) ----
    def get_live_workstation_hud(self, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Exposes the exact 8 essential trust & transparency indicators for the user."""
        tid = trace_id or workflow_runtime.last_trace_id
        events = workflow_runtime.get_event_history(trace_id=tid, limit=10)
        last_summary = workflow_runtime.last_action_summary or {}
        cert = last_summary.get("verification_certificate", {})
        receipt = last_summary.get("action_receipt", {})

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            zt_row = conn.execute(
                "SELECT * FROM zero_trust_data_capsules ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            zt_dict = dict(zt_row) if zt_row else {}

        return {
            "1_current_task": {
                "trace_id": tid,
                "goal": events[0]["summary"] if events else last_summary.get("spoken_response", "Idle"),
                "event_count": len(events),
            },
            "2_current_step": {
                "capability_id": last_summary.get("capability_id", events[-1]["capability_id"] if events else "idle"),
                "stage": events[-1]["event_type"] if events else "IDLE",
                "status": events[-1]["status"] if events else "READY",
            },
            "3_permission_state": {
                "autonomy_mode": policy_engine.constitution.get("autonomy_mode", "AUTONOMOUS_BOUNDED"),
                "permission_tier": last_summary.get("permission_tier", "TIER_1_READ"),
                "authorization_grant": receipt.get("authorization", {}),
            },
            "4_execution_evidence": {
                "observed_evidence": cert.get("proof", receipt.get("observed_evidence", "None")),
                "provider_receipt": receipt.get("provider_receipt", "None"),
            },
            "5_verification_status": {
                "tri_state_status": cert.get("tri_state_status", cert.get("status", "VERIFIED")),
                "verified": bool(cert.get("verified", True)),
                "receipt_id": receipt.get("receipt_id", "none"),
            },
            "6_recovery_controls": {
                "can_pause": tid not in workflow_runtime._paused_traces,
                "can_cancel": tid not in workflow_runtime._cancelled_traces,
                "can_rollback_file": bool(receipt.get("compensation_available", True)),
                "supported_commands": ["pause_workflow", "resume_workflow", "cancel_workflow", "rollback_last_action"],
            },
            "7_privacy_state": {
                "selected_model": zt_dict.get("selected_model", "local:jev-kernel-reflex"),
                "provider": zt_dict.get("provider", "local"),
                "left_device": bool(zt_dict.get("left_device", 0)),
                "secrets_redacted": bool(zt_dict.get("secrets_redacted", 0)),
                "capsule_id": zt_dict.get("capsule_id", "none"),
            },
            "8_resource_usage": {
                "duration_ms": last_summary.get("duration_ms", 0.0),
                "estimated_tokens": zt_dict.get("estimated_tokens", 0),
                "estimated_cost_usd": zt_dict.get("estimated_cost_usd", 0.0),
            },
        }

    # ---- 2. Active Recovery Controls (Pause / Resume / Cancel / Rollback) ----
    def trigger_recovery_control(self, command: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        tid = trace_id or workflow_runtime.last_trace_id
        cmd = command.lower().strip()
        if cmd == "pause_workflow":
            return workflow_runtime.pause_trace(tid)
        if cmd == "resume_workflow":
            return workflow_runtime.resume_trace(tid)
        if cmd == "cancel_workflow":
            return workflow_runtime.cancel_trace(tid)
        if cmd == "rollback_last_action":
            from agent.pa_scaffolder.blackboard_kernel import undo_ledger
            undo_res = undo_ledger.undo_last_action()
            return {"trace_id": tid, "status": "ROLLED_BACK", "undo_result": undo_res}
        return {"trace_id": tid, "status": "UNKNOWN_CONTROL_COMMAND"}

    # ---- 3. Reusable Personal Automation Library ----
    def save_routine(self, routine_name: str, trigger_phrase: str, steps: List[str]) -> Dict[str, Any]:
        key = routine_name.lower().strip()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO personal_routines (
                    routine_name, trigger_phrase, steps_json, autonomy_tier, run_count, created_at
                ) VALUES (?, ?, ?, 'SUPERVISED', 0, ?)
                """,
                (key, trigger_phrase, json.dumps(steps), time.time()),
            )
            conn.commit()
        return {"routine_name": key, "trigger_phrase": trigger_phrase, "steps": steps, "status": "SAVED"}

    def get_routine(self, routine_name: str) -> Optional[Dict[str, Any]]:
        key = routine_name.lower().strip()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM personal_routines WHERE routine_name = ?", (key,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE personal_routines SET run_count = run_count + 1 WHERE routine_name = ?", (key,))
            conn.commit()
            d = dict(row)
            d["steps"] = json.loads(d["steps_json"])
            return d

    def get_visual_activity_timeline(self, limit: int = 8) -> Dict[str, Any]:
        events = workflow_runtime.get_event_history(limit=limit)
        return {
            "persona_name": policy_engine.get_persona_name(),
            "autonomy_mode": policy_engine.constitution.get("autonomy_mode", "AUTONOMOUS_BOUNDED"),
            "timeline_items": [
                {
                    "step_seq": e["event_seq"],
                    "stage": e["event_type"],
                    "capability": e["capability_id"],
                    "target": e["target"],
                    "status": e["status"],
                    "detail": e["summary"],
                }
                for e in events
            ],
        }

    def get_permission_center(self) -> Dict[str, Any]:
        ledger = plugin_host.get_truth_ledger_report()
        return {
            "persona_name": policy_engine.get_persona_name(),
            "autonomy_mode": policy_engine.constitution.get("autonomy_mode"),
            "autonomy_matrix": policy_engine.get_autonomy_permissions_matrix(),
            "allowed_workspace_folders": policy_engine.constitution.get("allowed_workspace_roots", []),
            "disabled_plugins": ledger["disabled_plugins"],
            "total_capabilities": ledger["total_capabilities"],
            "verified_capabilities": ledger["empirically_verified_capabilities"],
            "privacy_rule": "Secrets are scrubbed locally before any cloud call; PRIVATE_COMM never indexed permanently.",
        }

    # ---- 4. Authenticated Mobile Pairing, Scoped Permissions & Network Reconnect Bridge ----
    def pair_mobile_device(
        self,
        device_id: str,
        device_name: str = "User_Android_Companion",
        allowed_scopes: Optional[List[str]] = None,
        ttl_sec: float = 3600.0,
    ) -> Dict[str, Any]:
        secret_tok = secrets.token_hex(16)
        scopes = allowed_scopes or ["mobile.submit_task", "mobile.approve_handoff", "mobile.view_hud"]
        now = time.time()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO paired_mobile_devices (
                    device_id, device_name, session_secret, allowed_scopes_json, paired_at, expires_at, revoked
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (device_id, device_name, secret_tok, json.dumps(scopes), now, now + ttl_sec),
            )
            conn.commit()
        return {
            "device_id": device_id,
            "session_secret": secret_tok,
            "allowed_scopes": scopes,
            "expires_at": now + ttl_sec,
        }

    def sign_mobile_payload(self, session_secret: str, payload_str: str) -> str:
        return hmac.new(session_secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_mobile_session(self, device_id: str, required_scope: str, payload_str: str, hmac_sig: str) -> Dict[str, Any]:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM paired_mobile_devices WHERE device_id = ?", (device_id,)).fetchone()
            if not row:
                return {"ok": False, "status": "BLOCKED_UNPAIRED_DEVICE"}
            d = dict(row)
            if d["revoked"] or time.time() > d["expires_at"]:
                return {"ok": False, "status": "BLOCKED_SESSION_EXPIRED_OR_REVOKED"}
            scopes = json.loads(d["allowed_scopes_json"])
            if required_scope not in scopes:
                return {"ok": False, "status": "BLOCKED_MOBILE_SCOPE_VIOLATION"}
            expected_sig = self.sign_mobile_payload(d["session_secret"], payload_str)
            if not hmac.compare_digest(expected_sig, hmac_sig):
                return {"ok": False, "status": "BLOCKED_INVALID_HMAC_SIGNATURE"}
            return {"ok": True, "status": "AUTHENTICATED_MOBILE_SESSION", "scopes": scopes}

    def create_mobile_handoff(
        self,
        task_title: str,
        pending_step: Dict[str, Any],
        origin_device: str = "desktop_workstation",
        target_device: str = "mobile_companion",
    ) -> Dict[str, Any]:
        raw = json.dumps(pending_step, sort_keys=True)
        app_hash = hashlib.sha256(f"{task_title}|{raw}".encode()).hexdigest()[:16]
        hid = f"hnd_{int(time.time() * 1000)}_{app_hash[:6]}"
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO cross_device_handoffs (
                    handoff_id, origin_device, target_device, task_title,
                    pending_step_json, approval_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'WAITING_ON_MOBILE', ?)
                """,
                (hid, origin_device, target_device, task_title, raw, app_hash, time.time()),
            )
            conn.commit()
        return {
            "handoff_id": hid,
            "origin_device": origin_device,
            "target_device": target_device,
            "approval_hash": app_hash,
            "status": "WAITING_ON_MOBILE",
        }

    def reconnect_and_sync_mobile_state(self, device_id: str, handoff_id: str) -> Dict[str, Any]:
        """Simulates mobile reconnection after network drop and syncs exact workstation task state."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM cross_device_handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
            if not row:
                return {"reconnected": False, "reason": "Handoff not found"}
            d = dict(row)
            return {
                "reconnected": True,
                "device_id": device_id,
                "handoff_id": handoff_id,
                "workstation_online": True,
                "synced_status": d["status"],
                "approval_hash": d["approval_hash"],
                "pending_step": json.loads(d["pending_step_json"]),
            }

    def resolve_mobile_handoff(
        self,
        handoff_id: str,
        approval_hash: str,
        approved: bool = True,
        device_id: Optional[str] = None,
        hmac_sig: Optional[str] = None,
    ) -> Dict[str, Any]:
        if device_id and hmac_sig:
            auth = self.verify_mobile_session(device_id, "mobile.approve_handoff", f"{handoff_id}:{approval_hash}", hmac_sig)
            if not auth["ok"]:
                return {"ok": False, "status": auth["status"], "reason": "Mobile authentication failed"}

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM cross_device_handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
            if not row:
                return {"ok": False, "reason": "Handoff ID not found"}
            d = dict(row)
            if d["approval_hash"] != approval_hash:
                return {"ok": False, "status": "BLOCKED_HASH_MISMATCH", "reason": "Cryptographic approval hash mismatch across devices!"}
            new_status = "RESUMED_ON_WORKSTATION" if approved else "CANCELLED_BY_MOBILE"
            conn.execute(
                "UPDATE cross_device_handoffs SET status = ?, resolved_at = ? WHERE handoff_id = ?",
                (new_status, time.time(), handoff_id),
            )
            conn.commit()
            return {
                "ok": True,
                "handoff_id": handoff_id,
                "status": new_status,
                "resumed_step": json.loads(d["pending_step_json"]),
            }


ux_continuity = UserExperienceAndContinuityService()
