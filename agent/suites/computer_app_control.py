from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.oryn.accessibility_engine import accessibility_engine
from agent.oryn.browser_engine import browser_engine
from agent.oryn.capability_registry import oryn_capability_registry
from agent.oryn.contracts import ChannelType, ComputerAction, ExecutionReceipt
from agent.oryn.native_api_engine import native_api_driver
from agent.oryn.runtime import oryn_runtime


class ComputerAppControlSuite:
    """Official Suite 5 (`computer_app_control`) in JVAI / ORYN's 7-Suite Architecture.

    Unifies all ORYN execution channels under a single suite interface:
      - Stage 1 (`native_api`): CLI, CSV/XLSX/SQLite, MCP Warm Pool, REST, OS Intents
      - Stage 2 (`dom`): Semantic DOM locators & zero-vision-token form/button actuation
      - Stage 3 (`cdp`): Raw Async Chrome DevTools Protocol WebSocket sessions
      - Stage 4 (`accessibility`): Cross-OS `aN -> wN -> rN` UIA/AT-SPI/Android tree & live target guard
    """

    SUITE_ID = "computer_app_control"

    def __init__(self) -> None:
        self.drivers = {
            "native_api": native_api_driver,
            "dom": browser_engine,
            "cdp": browser_engine,
            "accessibility": accessibility_engine,
        }

    @fault_recorder.guard(subsystem="suites.computer_app_control")
    async def execute_computer_objective(
        self,
        user_objective: str,
        target_app: str = "workstation",
        preferred_channel: Optional[ChannelType] = None,
        operation: str = "invoke_api",
        target_ref: Optional[str] = None,
        text: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()

        # 1. Jev System-1 Situational & Dynamic Model Directory Selection (0 Hardcoded Models)
        s1_decision = jev_ai_brain.analyze_situation(transcript=user_objective)

        # 2. ORYN Application Capability Discovery
        cap_route = oryn_capability_registry.select_optimal_channel(
            task_description=user_objective,
            target_app=target_app,
        )
        selected_channel: ChannelType = preferred_channel or cap_route["selected_channel"]
        if selected_channel not in self.drivers:
            selected_channel = "accessibility"

        action_id = f"oryn_{int(time.time() * 1000)}"
        action = ComputerAction(
            action_id=action_id,
            runtime_id=oryn_runtime.primary_runtime.runtime_id,
            channel=selected_channel,
            operation=operation,  # type: ignore[arg-type]
            target_ref=target_ref,
            text=text,
            payload=payload or {},
        )

        driver = self.drivers[selected_channel]
        receipt: ExecutionReceipt = await driver.execute(action)

        # Automatic single-step recovery / channel escalation if primary channel failed
        if not receipt.verified:
            recovered_action = await driver.recover(action, receipt)
            if recovered_action is not None:
                fallback_driver = self.drivers.get(recovered_action.channel, driver)
                receipt = await fallback_driver.execute(recovered_action)

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "suite": self.SUITE_ID,
            "objective": user_objective,
            "selected_channel": receipt.channel,
            "channel_confidence": cap_route["confidence"],
            "jev_selected_model": s1_decision.recommended_system2_model,
            "jev_selected_model_cost_per_1m_usd": s1_decision.selected_model_cost_per_1m_usd,
            "jev_selected_model_quality": s1_decision.selected_model_quality,
            "jev_required_quality_floor": s1_decision.required_quality_floor,
            "status": receipt.status,
            "verified": receipt.verified,
            "observed_evidence": receipt.observed_evidence,
            "receipt": receipt.to_dict(),
            "total_duration_ms": dur_ms,
        }


computer_app_control_suite = ComputerAppControlSuite()


# === ORYN 6-Stage Adaptive Computer Execution Integration ===
from agent.oryn.action_executor import oryn_action_executor
from agent.oryn.capability_registry import oryn_capability_registry
from agent.oryn.contracts import ActionBatch, ChannelType, ComputerAction
from agent.oryn.runtime import oryn_runtime
from agent.kernel.jev_ai_system1 import jev_ai_brain

async def _oryn_execute_computer_objective(
    self,
    user_objective: str,
    target_app: str = "workstation",
    preferred_channel: str | None = None,
    operation: str = "invoke_api",
    target_ref: str | None = None,
    text: str | None = None,
    payload: dict | None = None,
) -> dict:
    import time
    t0 = time.perf_counter()
    s1_decision = jev_ai_brain.analyze_situation(transcript=user_objective)
    cap_route = oryn_capability_registry.select_optimal_channel(
        task_description=user_objective,
        target_app=target_app,
    )
    selected_channel = preferred_channel or cap_route["selected_channel"]
    action = ComputerAction(
        action_id=f"oryn_{int(time.time() * 1000)}",
        runtime_id=oryn_runtime.primary_runtime.runtime_id,
        channel=selected_channel,
        operation=operation,
        target_ref=target_ref,
        text=text,
        payload=payload or {},
    )
    receipt = await oryn_action_executor.execute_action_with_recovery(action)
    dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "suite": "computer_app_control",
        "objective": user_objective,
        "selected_channel": receipt.channel,
        "channel_confidence": cap_route["confidence"],
        "jev_selected_model": s1_decision.recommended_system2_model,
        "jev_selected_model_cost_per_1m_usd": s1_decision.selected_model_cost_per_1m_usd,
        "jev_selected_model_quality": s1_decision.selected_model_quality,
        "jev_required_quality_floor": s1_decision.required_quality_floor,
        "status": receipt.status,
        "verified": receipt.verified,
        "observed_evidence": receipt.observed_evidence,
        "receipt": receipt.to_dict(),
        "total_duration_ms": dur_ms,
    }

async def _oryn_execute_action_batch(self, actions: list[ComputerAction], halt_on_modal: bool = True) -> dict:
    import time
    batch = ActionBatch(
        batch_id=f"batch_{int(time.time() * 1000)}",
        runtime_id=oryn_runtime.primary_runtime.runtime_id,
        actions=actions,
        halt_on_unexpected_modal=halt_on_modal,
    )
    return await oryn_action_executor.execute_batch(batch)

for _cls_name in ("UniversalComputerAppControlSuite", "ComputerAppControlSuite"):
    _cls = globals().get(_cls_name)
    if _cls is not None:
        _cls.execute_computer_objective = _oryn_execute_computer_objective
        _cls.execute_action_batch = _oryn_execute_action_batch

if "computer_app_control_suite" in globals():
    computer_app_control_suite.execute_computer_objective = _oryn_execute_computer_objective.__get__(computer_app_control_suite)
    computer_app_control_suite.execute_action_batch = _oryn_execute_action_batch.__get__(computer_app_control_suite)


# === ORYN_NON_DESTRUCTIVE_SUITE_BRIDGE ===
async def _oryn_execute_computer_objective(
    self,
    user_objective: str,
    target_app: str = "workstation",
    preferred_channel: str | None = None,
    operation: str = "invoke_api",
    target_ref: str | None = None,
    text: str | None = None,
    payload: dict | None = None,
) -> dict:
    from agent.kernel.computer_control import computer_control_broker
    return await computer_control_broker.execute_oryn_action(
        user_objective=user_objective,
        target_app=target_app,
        preferred_channel=preferred_channel,
        operation=operation,
        target_ref=target_ref,
        text=text,
        payload=payload,
    )


async def _oryn_execute_action_batch(
    self,
    actions: list,
    halt_on_modal: bool = True,
) -> dict:
    import time
    from agent.oryn.action_executor import oryn_action_executor
    from agent.oryn.contracts import ActionBatch
    from agent.oryn.runtime import oryn_runtime

    batch = ActionBatch(
        batch_id=f"batch_{int(time.time() * 1000)}",
        runtime_id=oryn_runtime.primary_runtime.runtime_id,
        actions=actions,
        halt_on_unexpected_modal=halt_on_modal,
    )
    return await oryn_action_executor.execute_batch(batch)


for _k, _v in list(globals().items()):
    if isinstance(_v, type) and ("Computer" in _k or "Suite" in _k):
        setattr(_v, "execute_computer_objective", _oryn_execute_computer_objective)
        setattr(_v, "execute_action_batch", _oryn_execute_action_batch)

if "computer_app_control_suite" in globals():
    _inst = globals()["computer_app_control_suite"]
    setattr(_inst.__class__, "execute_computer_objective", _oryn_execute_computer_objective)
    setattr(_inst.__class__, "execute_action_batch", _oryn_execute_action_batch)
