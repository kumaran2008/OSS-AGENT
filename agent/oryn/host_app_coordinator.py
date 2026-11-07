from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.workflow_runtime import workflow_runtime
from agent.oryn.action_executor import oryn_action_executor
from agent.oryn.capability_registry import oryn_capability_registry
from agent.oryn.contracts import ChannelType, ComputerAction, ExecutionReceipt
from agent.oryn.macro_memory import oryn_macro_memory
from agent.oryn.runtime import oryn_runtime


@dataclass(slots=True)
class SubtaskAssignment:
    subtask_id: str
    clause: str
    target_app: str
    selected_channel: ChannelType
    operation: str
    target_ref: Optional[str] = None
    text: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


class ORYNAppAgent:
    """UFO2-style AppAgent: executes a single application subtask using the fastest
    verified ORYN channel (Native API -> DOM -> CDP -> Accessibility -> Vision -> CUA).
    """

    def __init__(self, app_id: str) -> None:
        self.app_id = app_id
        self.capability = oryn_capability_registry.probe_application(app_id)

    @fault_recorder.guard(subsystem="oryn.app_agent")
    async def execute_subtask(self, assignment: SubtaskAssignment) -> Tuple[ComputerAction, ExecutionReceipt]:
        act = ComputerAction(
            action_id=f"{assignment.subtask_id}_{int(time.time() * 1000)}",
            runtime_id=oryn_runtime.primary_runtime.runtime_id,
            channel=assignment.selected_channel,
            operation=assignment.operation,  # type: ignore[arg-type]
            target_ref=assignment.target_ref,
            text=assignment.text,
            payload=assignment.payload,
        )
        receipt = await oryn_action_executor.execute_action_with_recovery(act)
        workflow_runtime.store_step_output_register(assignment.subtask_id, receipt.to_dict())
        return act, receipt


class ORYNHostAgentCoordinator:
    """UFO2-style HostAgent: decomposes cross-application user commands, schedules
    AppAgents sequentially under the desktop session lock, and promotes verified
    workflows into Task Macro Memory.
    """

    @staticmethod
    def decompose_into_app_subtasks(user_goal: str) -> List[SubtaskAssignment]:
        clauses = [
            c.strip()
            for c in re.split(r"\s*(?:,\s*and\s+|\band\s+then\b|\bthen\b|;)\s*", user_goal.strip(), flags=re.I)
            if len(c.strip()) >= 3
        ]
        if not clauses:
            clauses = [user_goal.strip()]

        assignments: List[SubtaskAssignment] = []
        for idx, clause in enumerate(clauses, 1):
            sid = f"step_{idx}"
            low = clause.lower()

            if any(w in low for w in ("spreadsheet", "csv", "excel", "xlsx", "save report", "write file")):
                app_id = "excel"
                ch: ChannelType = "native_api"
                op = "invoke_api"
                f_path = "workspace/oryn_generated_report.csv"
                payload = {
                    "sub_mode": "file_api",
                    "file_operation": "write_csv",
                    "file_path": f_path,
                    "headers": ["Step", "Clause", "VerifiedBy"],
                    "rows": [[sid, clause[:80], "ORYN_Stage1_NativeAPI"]],
                }
                t_ref = f_path
                txt = clause
            elif any(w in low for w in ("browser", "website", "web", "form", "submit", "search", "http")):
                app_id = "browser"
                ch = "dom"
                op = "click" if "click" in low or "submit" in low else ("type" if "type" in low or "fill" in low else "navigate")
                t_ref = "Submit" if op == "click" else "search_input"
                txt = clause
                payload = {"user_goal": clause}
            else:
                cap_info = oryn_capability_registry.select_optimal_channel(clause)
                app_id = cap_info["app_id"]
                ch = cap_info["selected_channel"]
                op = "click" if ch != "native_api" else "invoke_api"
                t_ref = clause[:60]
                txt = clause
                payload = (
                    {"sub_mode": "file_api", "file_operation": "write_text", "file_path": "workspace/oryn_note.txt", "content": clause}
                    if ch == "native_api"
                    else {"user_goal": clause}
                )

            assignments.append(
                SubtaskAssignment(
                    subtask_id=sid,
                    clause=clause,
                    target_app=app_id,
                    selected_channel=ch,
                    operation=op,
                    target_ref=t_ref,
                    text=txt,
                    payload=payload,
                )
            )
        return assignments

    @fault_recorder.guard(subsystem="oryn.host_coordinator")
    async def execute_cross_app_workflow(
        self,
        user_goal: str,
        capability_key: Optional[str] = None,
        auto_promote_macro: bool = True,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        cap_key = capability_key or f"oryn.workflow.{hash(user_goal.lower().strip()) & 0xFFFFFF:06x}"

        # 1. Check System-1 Task Macro Memory first (0 LLM calls if already learned)
        replayed = await oryn_macro_memory.replay_macro_if_available(cap_key)
        if replayed is not None and replayed.get("verified"):
            replayed["execution_mode"] = "SYSTEM1_GUARDED_MACRO_REPLAY"
            return replayed

        # 2. Evaluate situational complexity & dynamic model selection via Jev System 1
        s1 = jev_ai_brain.analyze_situation(transcript=user_goal)

        # 3. Decompose across AppAgents
        subtasks = self.decompose_into_app_subtasks(user_goal)
        executed_actions: List[ComputerAction] = []
        receipts: List[Dict[str, Any]] = []
        all_verified = True

        for st in subtasks:
            app_agent = ORYNAppAgent(st.target_app)
            act, rec = await app_agent.execute_subtask(st)
            executed_actions.append(act)
            receipts.append(rec.to_dict())
            if not rec.verified:
                all_verified = False
                break

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        batch_summary = {
            "status": "COMPLETED" if all_verified else "PARTIAL_OR_FAILED",
            "verified": all_verified,
            "execution_mode": "HOST_APP_AGENT_WORKFLOW",
            "objective": user_goal,
            "capability_key": cap_key,
            "jev_selected_model": s1.recommended_system2_model,
            "jev_model_cost_per_1m_usd": s1.selected_model_cost_per_1m_usd,
            "jev_model_quality": s1.selected_model_quality,
            "subtasks_count": len(subtasks),
            "completed_actions": len(receipts),
            "duration_ms": dur_ms,
            "receipts": receipts,
        }

        if all_verified and auto_promote_macro and executed_actions:
            recipe = oryn_macro_memory.promote_verified_batch_to_macro(
                capability_key=cap_key,
                app_identity="multi_app_host",
                actions=executed_actions,
                batch_result=batch_summary,
            )
            if recipe:
                batch_summary["promoted_macro_id"] = recipe.macro_id

        return batch_summary


oryn_host_coordinator = ORYNHostAgentCoordinator()
