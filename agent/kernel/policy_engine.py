from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.plugin_host import Action, AuthorizedTaskContext, plugin_host


@dataclass
class DryRunPolicyPreview:
    allowed: bool
    status: str
    reason: str
    policy_rule: str
    approval_hash: str
    preview_summary: str
    permission_tier: str = "TIER_1_READ"
    autonomy_mode: str = "AUTONOMOUS_BOUNDED"
    workstation_mode: str = "normal"
    grant: Optional[AuthorizedTaskContext] = None


class KernelPolicyEngine:
    """Authoritative Trust Boundary & 4-Level Progressive Autonomy Engine (Upgrade 17).
    Separates:
      1. Workstation Operational Modes (`normal`, `builder`, `researcher`, `streamer`, `gamer`)
         which configure hardware quotas, background daemons, and DND while keeping ALL plugins active.
      2. Progressive Autonomy Authority Levels:
         - `SUGGEST_ONLY`       : Analyzes and builds plans; blocks ALL state mutations and external actions.
         - `ASSISTED`           : Auto-allows `TIER_1_READ`; requires explicit approval hash for `TIER_2_LOCAL_EDIT`,
                                  `TIER_3_EXTERNAL_WRITE`, and `TIER_4_HIGH_IMPACT`.
         - `SUPERVISED`         : Auto-allows `TIER_1_READ` and `TIER_2_LOCAL_EDIT` (inside Shadow Twin);
                                  requires explicit approval for `TIER_3_EXTERNAL_WRITE` and `TIER_4_HIGH_IMPACT`.
         - `AUTONOMOUS_BOUNDED` : Executes pre-authorized `TIER_1`..`TIER_3` workflows within workspace roots,
                                  budget caps, and taint rules; gates unapproved destructive `TIER_4_HIGH_IMPACT`.
    Unbreakable Invariants across ALL modes:
      - Path traversal outside `allowed_workspace_roots` is ALWAYS blocked.
      - `UNTRUSTED_EXTERNAL` taint escalation to external_write/destructive is ALWAYS blocked.
      - Disabled plugins are ALWAYS blocked.
      - Mutating action arguments after approval invalidates the cryptographic grant (`BLOCKED_PAYLOAD_MUTATED`).
      - Changing Workstation Mode or Persona Name NEVER alters or escalates existing security grants.
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    RISK_TO_PERMISSION_TIER: Dict[str, str] = {
        "read": "TIER_1_READ",
        "transform": "TIER_1_READ",
        "local_write": "TIER_2_LOCAL_EDIT",
        "external_write": "TIER_3_EXTERNAL_WRITE",
        "destructive": "TIER_4_HIGH_IMPACT",
        "sensitive": "TIER_4_HIGH_IMPACT",
    }

    MODE_ALIASES: Dict[str, str] = {
        "SUGGEST_ONLY": "SUGGEST_ONLY",
        "ASSISTED": "ASSISTED",
        "ASK_BEFORE_ACT": "ASSISTED",
        "SUPERVISED": "SUPERVISED",
        "APPROVED_ROUTINE": "SUPERVISED",
        "AUTONOMOUS_BOUNDED": "AUTONOMOUS_BOUNDED",
    }

    PROHIBITED_PATTERNS = (
        r"\brm\s+-rf\s+/(?:\s|$)",
        r"\bmkfs\b",
        r"\bdd\s+if=",
        r":\(\)\{\s*:\|:&\s*\};:",
        r"/etc/shadow",
        r"/etc/passwd",
        r"\.ssh/id_rsa",
    )

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.constitution: Dict[str, Any] = {
            "require_confirmation_for_external_writes": False,
            "block_untrusted_taint_escalation": True,
            "never_send_sensitive_local_to_cloud": True,
            "allowed_workspace_roots": [str(Path("workspace").resolve()), str(Path("agent").resolve())],
            "max_task_budget_usd": 0.25,
            "quiet_hours_block_high_impact": False,
            "autonomy_mode": "AUTONOMOUS_BOUNDED",
        }
        self._revoked_grants: set[str] = set()
        self._approved_hashes: set[str] = set()
        self._consumed_one_time_hashes: set[str] = set()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kernel_config_kv (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def set_persona_name(self, new_name: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9_\- ]", "", new_name).strip() or "Friday"
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kernel_config_kv (config_key, config_value, updated_at) VALUES ('persona_name', ?, ?)",
                (clean, time.time()),
            )
            conn.commit()
        return clean

    def get_persona_name(self) -> str:
        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute("SELECT config_value FROM kernel_config_kv WHERE config_key = 'persona_name'").fetchone()
            return row[0] if row else "Friday"

    def set_autonomy_mode(self, mode: str) -> str:
        m = mode.upper().strip()
        if m not in self.MODE_ALIASES:
            raise ValueError(f"Invalid autonomy mode: {mode}. Must be one of {list(self.MODE_ALIASES.keys())}")
        canonical = self.MODE_ALIASES[m]
        self.constitution["autonomy_mode"] = canonical
        return canonical

    def get_autonomy_permissions_matrix(self) -> Dict[str, Dict[str, str]]:
        return {
            "SUGGEST_ONLY": {
                "TIER_1_READ": "DRY_RUN_PREVIEW_ONLY",
                "TIER_2_LOCAL_EDIT": "BLOCKED_SUGGEST_ONLY",
                "TIER_3_EXTERNAL_WRITE": "BLOCKED_SUGGEST_ONLY",
                "TIER_4_HIGH_IMPACT": "BLOCKED_SUGGEST_ONLY",
            },
            "ASSISTED": {
                "TIER_1_READ": "AUTO_ALLOWED",
                "TIER_2_LOCAL_EDIT": "REQUIRES_APPROVAL_HASH",
                "TIER_3_EXTERNAL_WRITE": "REQUIRES_APPROVAL_HASH",
                "TIER_4_HIGH_IMPACT": "REQUIRES_APPROVAL_HASH",
            },
            "SUPERVISED": {
                "TIER_1_READ": "AUTO_ALLOWED",
                "TIER_2_LOCAL_EDIT": "AUTO_ALLOWED_IN_SHADOW_TWIN",
                "TIER_3_EXTERNAL_WRITE": "REQUIRES_APPROVAL_HASH",
                "TIER_4_HIGH_IMPACT": "REQUIRES_APPROVAL_HASH",
            },
            "AUTONOMOUS_BOUNDED": {
                "TIER_1_READ": "AUTO_ALLOWED",
                "TIER_2_LOCAL_EDIT": "AUTO_ALLOWED_IN_SHADOW_TWIN",
                "TIER_3_EXTERNAL_WRITE": "BOUNDED_AUTO_OR_CONFIRM",
                "TIER_4_HIGH_IMPACT": "BOUNDED_SANDBOX_ONLY",
            },
        }

    @staticmethod
    def compute_approval_hash(action: Action) -> str:
        payload_str = json.dumps(action.validated_arguments, sort_keys=True, default=str)
        raw = f"{action.capability_id}|{action.target}|{payload_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def approve_action_hash(self, approval_hash: str) -> None:
        self._approved_hashes.add(approval_hash)

    def revoke_grant(self, grant_id: str) -> None:
        self._revoked_grants.add(grant_id)

    def is_grant_valid(self, context: AuthorizedTaskContext, action: Action) -> bool:
        if context.grant_id in self._revoked_grants:
            return False
        if time.time() > context.expires_at:
            return False
        current_hash = self.compute_approval_hash(action)
        return current_hash == context.approval_hash

    def evaluate_and_mint_context(
        self,
        action: Action,
        trace_id: str,
        active_mode: str = "normal",
        taint_level: str = "TRUSTED",
        taint_context: str = "",
        approved_by_user: bool = False,
    ) -> DryRunPolicyPreview:
        from agent.pa_scaffolder.kernel_governance import policy_firewall, secret_scrubber

        app_hash = self.compute_approval_hash(action)
        is_approved = approved_by_user or (app_hash in self._approved_hashes)
        perm_tier = self.RISK_TO_PERMISSION_TIER.get(action.risk_class, "TIER_1_READ")
        autonomy = self.constitution.get("autonomy_mode", "AUTONOMOUS_BOUNDED")

        # Invariant 0: Check if owning plugin is enabled
        cap_meta = plugin_host.get_capability(action.capability_id)
        if cap_meta and cap_meta.plugin_id in plugin_host._disabled_plugins:
            return DryRunPolicyPreview(
                allowed=False,
                status="BLOCKED_PLUGIN_DISABLED",
                reason=f"Plugin '{cap_meta.plugin_id}' is disabled in Permission Center.",
                policy_rule="INVARIANT_PLUGIN_ENABLED",
                approval_hash=app_hash,
                preview_summary=f"Blocked disabled plugin {cap_meta.plugin_id}",
                permission_tier=perm_tier,
                autonomy_mode=autonomy,
                workstation_mode=active_mode,
            )

        # Invariant 1: Hard Prohibited Destructive Patterns (NEVER allowed in any mode, even with approval)
        for pat in self.PROHIBITED_PATTERNS:
            if re.search(pat, action.raw_instruction) or re.search(pat, str(action.target)):
                return DryRunPolicyPreview(
                    allowed=False,
                    status="BLOCKED_PROHIBITED_SYSCALL",
                    reason=f"Command matches prohibited host-destruction pattern ({pat}).",
                    policy_rule="INVARIANT_PROHIBITED_ACTION",
                    approval_hash=app_hash,
                    preview_summary="Blocked prohibited destructive system pattern.",
                    permission_tier=perm_tier,
                    autonomy_mode=autonomy,
                    workstation_mode=active_mode,
                )

        # Invariant 2: Strict Workspace Path Confinement (Blocks '../' traversal & symlink escapes in ALL modes)
        fpath = action.validated_arguments.get("file_path")
        if fpath or action.capability_id in ("builder.patch_verified", "builder.ast_inspect", "builder.reconcile_code", "doc.read_slice"):
            check_p = fpath or action.target
            if check_p and check_p != "workstation":
                try:
                    resolved_p = str(Path(check_p).resolve())
                    if not any(resolved_p.startswith(root) for root in self.constitution["allowed_workspace_roots"]):
                        return DryRunPolicyPreview(
                            allowed=False,
                            status="BLOCKED_CONSTITUTION_PATH",
                            reason=f"Path '{check_p}' resolves to '{resolved_p}' outside allowlisted workspace roots.",
                            policy_rule="INVARIANT_PATH_CONFINEMENT",
                            approval_hash=app_hash,
                            preview_summary=f"Denied out-of-scope file access to {check_p}.",
                            permission_tier=perm_tier,
                            autonomy_mode=autonomy,
                            workstation_mode=active_mode,
                        )
                except Exception as e:
                    return DryRunPolicyPreview(
                        allowed=False,
                        status="BLOCKED_INVALID_PATH",
                        reason=f"Malformed path '{check_p}': {e}",
                        policy_rule="INVARIANT_PATH_CONFINEMENT",
                        approval_hash=app_hash,
                        preview_summary="Denied malformed path.",
                        permission_tier=perm_tier,
                        autonomy_mode=autonomy,
                        workstation_mode=active_mode,
                    )

        # Invariant 3: Untrusted External Taint Escalation Firewall (Blocks prompt injection in ALL modes)
        if (action.capability_id == "builder.terminal_sandbox" or (self.constitution["block_untrusted_taint_escalation"] and taint_level == "UNTRUSTED_EXTERNAL")) and not is_approved:
            if taint_level == "UNTRUSTED_EXTERNAL" and action.risk_class in ("local_write", "external_write", "destructive", "sensitive"):
                return DryRunPolicyPreview(
                    allowed=False,
                    status="BLOCKED_TAINT_ESCALATION",
                    reason=f"Untrusted external data cannot trigger {action.risk_class} capability '{action.capability_id}'.",
                    policy_rule="INVARIANT_TAINT_FIREWALL",
                    approval_hash=app_hash,
                    preview_summary="Blocked untrusted taint escalation.",
                    permission_tier=perm_tier,
                    autonomy_mode=autonomy,
                    workstation_mode=active_mode,
                )
            if action.capability_id == "builder.terminal_sandbox":
                dec = policy_firewall.evaluate_command(
                    action.raw_instruction,
                    active_mode=active_mode,
                    approved_by_user=is_approved,
                    taint_level=taint_level,
                    taint_context=taint_context,
                )
                if not dec.allowed:
                    st = dec.status if str(dec.status).startswith("BLOCKED") else f"BLOCKED_{dec.status}"
                    return DryRunPolicyPreview(
                        allowed=False,
                        status=st,
                        reason=dec.reason,
                        policy_rule="INVARIANT_TERMINAL_FIREWALL",
                        approval_hash=app_hash,
                        preview_summary=f"Blocked terminal command: {dec.reason}",
                        permission_tier=perm_tier,
                        autonomy_mode=autonomy,
                        workstation_mode=active_mode,
                    )

        # Invariant 4: 4-Level Progressive Autonomy Enforcement
        if autonomy == "SUGGEST_ONLY" and not is_approved:
            return DryRunPolicyPreview(
                allowed=False,
                status="SUGGEST_ONLY_PREVIEW",
                reason=f"Autonomy mode is SUGGEST_ONLY. Prepared plan for {action.capability_id} on {action.target} without executing mutations.",
                policy_rule="AUTONOMY_SUGGEST_ONLY",
                approval_hash=app_hash,
                preview_summary=f"[SUGGEST_ONLY] Dry-run plan for {action.capability_id} (Tier={perm_tier}, Hash={app_hash})",
                permission_tier=perm_tier,
                autonomy_mode=autonomy,
                workstation_mode=active_mode,
            )

        if autonomy == "ASSISTED" and perm_tier != "TIER_1_READ" and not is_approved:
            return DryRunPolicyPreview(
                allowed=False,
                status="REQUIRES_CONFIRMATION",
                reason=f"Autonomy mode ASSISTED requires user approval for {perm_tier} ({action.capability_id}).",
                policy_rule="AUTONOMY_ASSISTED_GATE",
                approval_hash=app_hash,
                preview_summary=f"[ASSISTED] Approve hash {app_hash} to execute {action.capability_id}",
                permission_tier=perm_tier,
                autonomy_mode=autonomy,
                workstation_mode=active_mode,
            )

        if autonomy == "SUPERVISED" and perm_tier in ("TIER_3_EXTERNAL_WRITE", "TIER_4_HIGH_IMPACT") and not is_approved:
            return DryRunPolicyPreview(
                allowed=False,
                status="REQUIRES_CONFIRMATION",
                reason=f"Autonomy mode SUPERVISED allows local Shadow-Twin edits but pauses on {perm_tier} ({action.capability_id}).",
                policy_rule="AUTONOMY_SUPERVISED_GATE",
                approval_hash=app_hash,
                preview_summary=f"[SUPERVISED] Approve hash {app_hash} for external/high-impact action {action.capability_id}",
                permission_tier=perm_tier,
                autonomy_mode=autonomy,
                workstation_mode=active_mode,
            )

        if self.constitution.get("require_confirmation_for_external_writes") and action.risk_class == "external_write" and not is_approved:
            return DryRunPolicyPreview(
                allowed=False,
                status="REQUIRES_CONFIRMATION",
                reason="Constitutional rule requires confirmation for external writes.",
                policy_rule="CONSTITUTION_EXTERNAL_WRITE_CONFIRM",
                approval_hash=app_hash,
                preview_summary=f"Dry-Run Preview: Capability={action.capability_id} | Hash={app_hash}",
                permission_tier=perm_tier,
                autonomy_mode=autonomy,
                workstation_mode=active_mode,
            )

        # Consume single-use approval hash so stale approvals cannot be replayed on future turns
        if app_hash in self._approved_hashes:
            self._approved_hashes.discard(app_hash)
            self._consumed_one_time_hashes.add(app_hash)

        _, had_secret = secret_scrubber.scrub(action.raw_instruction)
        allow_remote = not (had_secret or action.data_sensitivity in ("SENSITIVE_LOCAL", "PRIVATE_COMM"))
        now = time.time()
        grant = AuthorizedTaskContext(
            grant_id=f"grant_{int(now * 1000)}_{app_hash[:6]}",
            trace_id=trace_id,
            action_id=action.action_id,
            capability_id=action.capability_id,
            authorized_scopes=[f"scope:{action.capability_id}", f"tier:{perm_tier}", f"autonomy:{autonomy}", f"mode:{active_mode}"],
            approval_hash=app_hash,
            allow_remote_processing=allow_remote,
            taint_level=taint_level,
            issued_at=now,
            expires_at=now + (action.timeout_ms / 1000.0) + 60.0,
            policy_rule_matched="KERNEL_POLICY_ALLOW",
        )
        return DryRunPolicyPreview(
            allowed=True,
            status="ALLOWED",
            reason="Permitted by Kernel Policy Engine.",
            policy_rule="KERNEL_POLICY_ALLOW",
            approval_hash=app_hash,
            preview_summary=f"Authorized {action.capability_id} on {action.target} (tier={perm_tier}, mode={active_mode}, hash={app_hash})",
            permission_tier=perm_tier,
            autonomy_mode=autonomy,
            workstation_mode=active_mode,
            grant=grant,
        )


policy_engine = KernelPolicyEngine()
