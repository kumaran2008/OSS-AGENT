from __future__ import annotations

import time
from typing import Any, Dict, List

from agent.kernel.plugin_host import (
    Action,
    ActionResult,
    AuthorizedTaskContext,
    Capability,
    VerificationResult,
    plugin_host,
)
from agent.oryn.host_app_coordinator import oryn_host_coordinator


class ORYNComputerControlPlugin:
    """Mounts ORYN 6-Stage Adaptive Computer Execution into the Kernel PluginHostRegistry."""

    plugin_id = "plugin.oryn_computer"
    api_version = "1.0.0"

    def discover_capabilities(self) -> List[Capability]:
        return [
            Capability(
                id="oryn.computer_execute",
                version="1.0.0",
                plugin_id=self.plugin_id,
                description="Executes cross-application computer tasks via ORYN 6-stage hybrid engine.",
                execution_backend="OFFICIAL_API",
                risk_class="local_write",
                data_sensitivity="PUBLIC",
                preconditions=["workspace_root_allowlisted"],
                postconditions=["oryn_layer7_verified"],
            ),
            Capability(
                id="oryn.macro_replay",
                version="1.0.0",
                plugin_id=self.plugin_id,
                description="Replays verified GuardedMacroRecipes in System 1 with zero LLM tokens.",
                execution_backend="LOCAL_SANDBOX",
                risk_class="read",
                data_sensitivity="PUBLIC",
                preconditions=["macro_fingerprint_matched"],
                postconditions=["all_steps_verified"],
            ),
        ]

    def health_check(self) -> Dict[str, Any]:
        caps = self.discover_capabilities()
        return {
            "plugin_id": self.plugin_id,
            "status": "HEALTHY",
            "healthy": True,
            "capabilities_count": len(caps),
        }

    async def execute(self, action: Action, context: AuthorizedTaskContext) -> ActionResult:
        res = await oryn_host_coordinator.execute_cross_app_workflow(
            user_goal=action.raw_instruction,
            capability_key=action.capability_id,
        )
        ok = bool(res.get("verified"))
        return ActionResult(
            action_id=action.action_id,
            capability_id=action.capability_id,
            status="COMPLETED" if ok else "FAILED",
            raw_legacy_dict=res,
            provider_receipt=str(res.get("promoted_macro_id") or res.get("macro_id") or "oryn_verified"),
            evidence_refs=[r.get("observed_evidence", "") for r in res.get("receipts", [])],
        )

    def verify(self, action: Action, result: ActionResult) -> VerificationResult:
        ok = result.status == "COMPLETED" and bool(result.raw_legacy_dict.get("verified"))
        return VerificationResult(
            action_id=action.action_id,
            capability_id=action.capability_id,
            status="COMPLETED" if ok else "FAILED",
            verified=ok,
            evidence_type="ORYN_LAYER7_UNIVERSAL_VERIFIER",
            observed_evidence="; ".join(result.evidence_refs)[:240] or "Verified by ORYN Layer 7",
            timestamp=time.time(),
        )


oryn_computer_plugin = ORYNComputerControlPlugin()
plugin_host.register_plugin(oryn_computer_plugin)
