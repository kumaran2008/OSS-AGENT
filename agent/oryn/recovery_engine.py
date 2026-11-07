from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.oryn.contracts import (
    ChannelType,
    ComputerAction,
    ExecutionReceipt,
)


@dataclass(slots=True)
class RecoveryDecision:
    strategy: str  # "WAIT_AND_RETRY" | "REBIND_REF" | "SWITCH_CHANNEL" | "ESCALATE_SYSTEM2" | "HALT"
    next_channel: ChannelType
    replacement_action: Optional[ComputerAction]
    escalated_model_id: Optional[str]
    reason: str


class ORYNRecoveryEngine:
    """Layer 7b: Deterministic Recovery Finite State Machine (FSM) for ORYN.

    Ladder of recovery when an action fails verification:
      Step 1 (`WAIT_AND_RETRY`): Wait 150ms for UI/DOM settle and retry once if transient.
      Step 2 (`REBIND_REF`): Refresh DOM/AX tree and re-run Jev semantic ref selection.
      Step 3 (`SWITCH_CHANNEL`): Escalate along the 6-stage channel hierarchy.
      Step 4 (`ESCALATE_SYSTEM2`): Query Jev's dynamic SQLite model directory for a higher-quality model.
    """

    CHANNEL_ESCALATION_ORDER: List[ChannelType] = [
        "native_api",
        "dom",
        "cdp",
        "accessibility",
        "vision",
        "frontier_cua",
    ]

    @fault_recorder.guard(subsystem="oryn.recovery_engine")
    async def plan_recovery(
        self,
        failed_action: ComputerAction,
        failed_receipt: ExecutionReceipt,
        attempt: int = 1,
    ) -> RecoveryDecision:
        if failed_receipt.status == "BLOCKED_POLICY":
            return RecoveryDecision(
                strategy="HALT",
                next_channel=failed_action.channel,
                replacement_action=None,
                escalated_model_id=None,
                reason=f"Halted by Kernel Policy Engine: {failed_receipt.observed_evidence}",
            )

        # Step 1: Stale AX/DOM ref -> refresh tree and clear fingerprint lock so Jev rebinds ref
        if failed_receipt.status == "STALE_TARGET_ABORTED" or failed_receipt.error_code in (
            "STALE_OR_MISSING_AX_REF",
            "CDP_SELECTOR_NOT_FOUND",
        ):
            if attempt == 1:
                await asyncio.sleep(0.15)
                rebound = ComputerAction(
                    action_id=f"{failed_action.action_id}_rebind_{attempt}",
                    runtime_id=failed_action.runtime_id,
                    channel=failed_action.channel,
                    operation=failed_action.operation,
                    target_ref=failed_action.target_ref,
                    coordinates=failed_action.coordinates,
                    text=failed_action.text,
                    keys=failed_action.keys,
                    wait_ms=max(150, failed_action.wait_ms),
                    settle_ui=True,
                    payload=failed_action.payload,
                    expected_ref_fingerprint=None,
                )
                return RecoveryDecision(
                    strategy="REBIND_REF",
                    next_channel=failed_action.channel,
                    replacement_action=rebound,
                    escalated_model_id=None,
                    reason="Refreshed live UI tree and cleared stale fingerprint to rebind target_ref.",
                )

        # Step 2: Escalate execution channel along the 6-stage fallback ladder
        curr_ch = failed_action.channel
        idx = self.CHANNEL_ESCALATION_ORDER.index(curr_ch) if curr_ch in self.CHANNEL_ESCALATION_ORDER else 0
        if idx + 1 < len(self.CHANNEL_ESCALATION_ORDER):
            next_ch = self.CHANNEL_ESCALATION_ORDER[idx + 1]
            # If escalating from native_api to dom/accessibility, adapt invoke_api to click/navigate
            next_op = failed_action.operation
            if next_op == "invoke_api" and next_ch in ("dom", "cdp", "accessibility"):
                next_op = "navigate" if (failed_action.target_ref or "").startswith("http") else "click"

            switched = ComputerAction(
                action_id=f"{failed_action.action_id}_esc_{next_ch}",
                runtime_id=failed_action.runtime_id,
                channel=next_ch,
                operation=next_op,
                target_ref=failed_action.target_ref,
                coordinates=failed_action.coordinates,
                text=failed_action.text,
                keys=failed_action.keys,
                wait_ms=failed_action.wait_ms,
                settle_ui=True,
                payload=failed_action.payload,
                expected_ref_fingerprint=None,
            )
            return RecoveryDecision(
                strategy="SWITCH_CHANNEL",
                next_channel=next_ch,
                replacement_action=switched,
                escalated_model_id=None,
                reason=f"Channel '{curr_ch}' failed ({failed_receipt.error_code}); escalating to '{next_ch}'.",
            )

        # Step 3: Dynamic System-2 Model Escalation from SQLite Model Directory (0 Hardcoded Models)
        s1_esc = jev_ai_brain.analyze_situation(
            transcript=f"Recover failed computer action {failed_action.operation} on {failed_action.target_ref}",
            retry_attempt=attempt + 1,
            previous_error=failed_receipt.observed_evidence,
        )
        return RecoveryDecision(
            strategy="ESCALATE_SYSTEM2",
            next_channel="frontier_cua",
            replacement_action=None,
            escalated_model_id=s1_esc.recommended_system2_model,
            reason=(
                f"All local channels exhausted; escalating to System-2 model "
                f"'{s1_esc.recommended_system2_model}' (Q={s1_esc.selected_model_quality})."
            ),
        )


oryn_recovery_engine = ORYNRecoveryEngine()
