from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from agent.kernel.fault_recorder import fault_recorder
from agent.oryn.accessibility_engine import accessibility_engine
from agent.oryn.browser_engine import browser_engine
from agent.oryn.contracts import (
    ActionBatch,
    ChannelType,
    ComputerAction,
    ExecutionDriver,
    ExecutionReceipt,
)
from agent.oryn.native_api_engine import native_api_driver
from agent.oryn.recovery_engine import oryn_recovery_engine
from agent.oryn.verifier import oryn_verifier


class ORYNActionBatchExecutor:
    """Executes single ComputerActions and HCU-style 64-action speculative batches
    with per-step postcondition verification and automatic Layer-7 recovery.
    """

    def __init__(self) -> None:
        self.drivers: Dict[ChannelType, ExecutionDriver] = {
            "native_api": native_api_driver,
            "dom": browser_engine,
            "cdp": browser_engine,
            "accessibility": accessibility_engine,
        }

    def register_driver(self, channel: ChannelType, driver: ExecutionDriver) -> None:
        self.drivers[channel] = driver

    @fault_recorder.guard(subsystem="oryn.action_executor")
    async def execute_action_with_recovery(
        self,
        action: ComputerAction,
        max_recovery_attempts: int = 2,
    ) -> ExecutionReceipt:
        current_action = action
        attempt = 0

        while True:
            if current_action.operation == "wait":
                t0 = time.perf_counter()
                wait_sec = max(0.05, float(current_action.wait_ms or 150) / 1000.0)
                await asyncio.sleep(wait_sec)
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=current_action.action_id,
                    runtime_id=current_action.runtime_id,
                    channel=current_action.channel,
                    status="COMPLETED",
                    verified=True,
                    duration_ms=dur,
                    observed_evidence=f"In-call settle wait completed ({dur}ms).",
                )

            driver = self.drivers.get(current_action.channel, accessibility_engine)
            raw_receipt = await driver.execute(current_action)
            verified_receipt = await oryn_verifier.verify_execution(current_action, raw_receipt)

            if verified_receipt.verified or attempt >= max_recovery_attempts:
                return verified_receipt

            attempt += 1
            decision = await oryn_recovery_engine.plan_recovery(
                failed_action=current_action,
                failed_receipt=verified_receipt,
                attempt=attempt,
            )
            verified_receipt.recovery_suggestion = decision.reason
            if decision.replacement_action is None or decision.strategy in ("HALT", "ESCALATE_SYSTEM2"):
                verified_receipt.output_data["recovery_decision"] = {
                    "strategy": decision.strategy,
                    "escalated_model_id": decision.escalated_model_id,
                    "reason": decision.reason,
                }
                return verified_receipt

            current_action = decision.replacement_action

    @fault_recorder.guard(subsystem="oryn.action_executor")
    async def execute_batch(self, batch: ActionBatch) -> Dict[str, Any]:
        """Executes up to 64 ref-bound actions sequentially, halting immediately if
        an unexpected modal appears or an unrecoverable state drift occurs.
        """
        t0 = time.perf_counter()
        receipts: List[Dict[str, Any]] = []
        completed_count = 0
        aborted_reason: Optional[str] = None

        for idx, act in enumerate(batch.actions):
            rec = await self.execute_action_with_recovery(act)
            receipts.append(rec.to_dict())

            if not rec.verified:
                aborted_reason = (
                    f"Batch halted at step {idx + 1}/{len(batch.actions)} ({act.action_id}): "
                    f"{rec.observed_evidence}"
                )
                break

            completed_count += 1
            if batch.halt_on_unexpected_modal and rec.ax_diff and rec.ax_diff.modal_appeared:
                aborted_reason = f"Batch paused at step {idx + 1}: unexpected modal dialog appeared."
                break

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        all_ok = completed_count == len(batch.actions) and aborted_reason is None
        return {
            "batch_id": batch.batch_id,
            "runtime_id": batch.runtime_id,
            "status": "COMPLETED" if all_ok else "PARTIAL_OR_HALTED",
            "verified": all_ok,
            "total_actions": len(batch.actions),
            "completed_actions": completed_count,
            "aborted_reason": aborted_reason,
            "duration_ms": dur_ms,
            "receipts": receipts,
        }


oryn_action_executor = ORYNActionBatchExecutor()
