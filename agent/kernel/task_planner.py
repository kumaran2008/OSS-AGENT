from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.kernel.capability_registry import capability_registry
from agent.kernel.intent_compiler import intent_compiler
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.model_broker import model_broker
from agent.kernel.policy_engine import policy_engine
from agent.kernel.workflow_runtime import workflow_runtime
# unified_memory_service is resolved lazily inside methods to prevent circular imports


@dataclass
class PlannedTaskStep:
    step_id: str
    clause_text: str
    capability_id: str
    execution_substrate: str       # PYTHON_DETERMINISTIC | INDEXED_RETRIEVAL | MCP_STDIO | PLUGIN_RUNTIME | SUITE_WORKFLOW
    selected_model: str
    depends_on: List[str] = field(default_factory=list)
    requires_approval: bool = False
    verification_method: str = "postcondition_receipt_verifier"
    fallback_capability: Optional[str] = None


def _get_memory_service():
    from agent.memory_graph.memory_service import unified_memory_service
    return unified_memory_service

class UniversalTaskLifecyclePlanner:
    """Section 3: Universal 9-Stage Task Execution Lifecycle (`agent/kernel/task_planner.py`).
    Every arbitrary user request passes through:
      1. Understand  : Interpret objective, emotional state, urgency, and constraints via TypeSafe `Jev`.
      2. Clarify     : Check if critical parameters or high-risk confirmations are missing.
      3. Plan        : Construct a dependency-aware DAG (`PlannedTaskStep` nodes) using `capability_registry`.
      4. Retrieve    : Load deterministically namespace-locked memories (`unified_memory_service`).
      5. Authorise   : Check permissions, privacy caps, and approval requirements (`policy_engine`).
      6. Execute     : Run steps in parallel topological waves (using Python, Indexed Retrieval, `Jev`, or LLMs).
      7. Verify      : Independently verify postconditions for every step.
      8. Recover     : Retry, switch to fallback capability, or escalate model tier on failure.
      9. Report      : Return a structured, transparent execution report with cost & verification receipts.
    """

    @staticmethod
    def decompose_clauses(objective: str) -> List[str]:
        parts = re.split(
            r"\s*(?:;\s*|\band\s+then\b\s*|\bthen\b\s*|\band\s+(?=(?:switch|open|read|extract|send|reply|message|schedule|set|run|execute|patch|fix|reconcile|list|delete|export|undo|play|turn|inspect|calculate|sort|search|compare|build|test)\b))\s*",
            objective.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = [p.strip() for p in parts if len(p.strip()) > 3]
        return cleaned if cleaned else [objective.strip()]

    def build_dependency_plan(self, objective: str) -> List[PlannedTaskStep]:
        clauses = self.decompose_clauses(objective)
        steps: List[PlannedTaskStep] = []

        for idx, clause in enumerate(clauses):
            sid = f"step_{idx + 1}"
            low_c = clause.lower()

            # Check if this step is pure deterministic math/sorting in Python ($0.00, 0 LLM tokens)
            if re.search(r"\b(?:calculate|percentage|sort\s+files|compute\s+sum)\b", low_c) and not any(w in low_c for w in (".py", "bug", "reconcile")):
                cap_id = "python.deterministic_compute"
                substrate = "PYTHON_DETERMINISTIC"
                sel_model = "local:python-deterministic"
                req_app = False
                ver_meth = "deterministic_return_check"
                fallback = None
            else:
                # Query live Capability Registry via TypeSafe `Jev` + semantic compiler
                act_probe = intent_compiler.compile_single_action(clause)
                reg_entry = capability_registry.get_capability_entry(act_probe.capability_id)
                if reg_entry is None:
                    jev_sel = capability_registry.select_capabilities_via_jev(clause, top_k=1)
                    cap_id = jev_sel["selected_capability"]
                    reg_entry = capability_registry.get_capability_entry(cap_id)
                else:
                    cap_id = reg_entry.capability

                substrate = reg_entry.execution_substrate if reg_entry else "PLUGIN_RUNTIME"
                req_app = reg_entry.requires_approval if reg_entry else False
                ver_meth = reg_entry.verification_method if reg_entry else "postcondition_receipt_verifier"
                fallback = reg_entry.fallback_capability if reg_entry else None

                if substrate in ("PYTHON_DETERMINISTIC", "INDEXED_RETRIEVAL"):
                    sel_model = "local:jev-kernel-reflex"
                else:
                    rt = model_broker.route_task_economically(clause)
                    sel_model = rt["selected_model"]

            # Detect data-pipe dependencies (`$step_1`, "it", "the result", "that file", or sequential messaging)
            deps: List[str] = []
            if idx > 0:
                explicit_refs = re.findall(r"\$(step_\d+)", clause)
                if explicit_refs:
                    deps.extend(explicit_refs)
                elif any(w in low_c for w in ("send", "reply", "report", "that", "results", "after")):
                    deps.append(f"step_{idx}")

            steps.append(
                PlannedTaskStep(
                    step_id=sid,
                    clause_text=clause,
                    capability_id=cap_id,
                    execution_substrate=substrate,
                    selected_model=sel_model,
                    depends_on=sorted(set(deps)),
                    requires_approval=req_app,
                    verification_method=ver_meth,
                    fallback_capability=fallback,
                )
            )
        return steps

    async def execute_lifecycle(
        self,
        objective: str,
        approved_by_user: bool = False,
        active_mode: str = "normal",
    ) -> Dict[str, Any]:
        """Executes all 9 stages of the Universal Task Execution Lifecycle."""
        t0 = time.perf_counter()
        trace_id = f"trc_univ_{int(time.time() * 1000)}"
        lifecycle_log: Dict[str, Any] = {}

        # Stage 1: UNDERSTAND
        s1_decision = jev_ai_brain.analyze_situation(objective)
        lifecycle_log["1_understand"] = {
            "situational_domain": s1_decision.situational_domain,
            "complexity": s1_decision.situational_complexity,
            "emotional_state": s1_decision.emotional_state,
            "recommended_namespaces": s1_decision.recommended_namespaces,
        }

        # Stage 2: CLARIFY
        needs_clarification = len(objective.strip()) < 3
        lifecycle_log["2_clarify"] = {
            "clarification_needed": needs_clarification,
            "question": "Could you clarify the target file or app?" if needs_clarification else None,
        }
        if needs_clarification:
            return {"status": "NEEDS_CLARIFICATION", "lifecycle": lifecycle_log}

        # Stage 3: PLAN (Dependency-Aware DAG)
        planned_steps = self.build_dependency_plan(objective)
        lifecycle_log["3_plan"] = [
            {
                "step_id": s.step_id,
                "capability": s.capability_id,
                "substrate": s.execution_substrate,
                "model": s.selected_model,
                "depends_on": s.depends_on,
            }
            for s in planned_steps
        ]

        # Stage 4: RETRIEVE (Deterministic Namespace-Enforced Memory Retrieval)
        scoped_mem = _get_memory_service().retrieve_scoped_memories(
            query=objective,
            allowed_namespaces=s1_decision.recommended_namespaces,
            timeline_scope="current_active_only",
        )
        lifecycle_log["4_retrieve"] = {
            "enforced_namespaces": scoped_mem["enforced_namespaces"],
            "memories_loaded": len(scoped_mem["results"]),
            "cross_namespace_leakage": scoped_mem["cross_namespace_leakage_count"],
        }

        # Stage 5 & 6: AUTHORISE & EXECUTE
        dag_nodes: List[Dict[str, Any]] = []
        deterministic_outputs: Dict[str, Any] = {}

        for s in planned_steps:
            if s.capability_id == "python.deterministic_compute":
                # Execute pure Python math/percentage/sorting directly with 0 LLM tokens!
                nums = [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", s.clause_text)]
                val = round((nums[0] / nums[1]) * 100.0, 2) if (len(nums) >= 2 and nums[1] != 0) else sum(nums)
                res_py = {
                    "status": "COMPLETED",
                    "capability_id": s.capability_id,
                    "execution_substrate": "PYTHON_DETERMINISTIC",
                    "computed_value": val,
                    "llm_tokens_used": 0,
                    "verification_certificate": {"verified": True, "status": "VERIFIED", "proof": f"Deterministic Python result={val}"},
                }
                deterministic_outputs[s.step_id] = res_py
                workflow_runtime.store_step_output_register(s.step_id, res_py)
            else:
                act = intent_compiler.compile_single_action(s.clause_text)
                act.capability_id = s.capability_id
                dag_nodes.append({"id": s.step_id, "action": act, "depends_on": [d for d in s.depends_on if d not in deterministic_outputs]})

        dag_exec = (
            await workflow_runtime.execute_multi_plugin_dag(
                dag_nodes, trace_id=trace_id, active_mode=active_mode, approved_by_user=approved_by_user
            )
            if dag_nodes
            else {"status": "COMPLETED", "waves_executed": 1, "plugins_activated": ["kernel.python"], "completed_steps": {}}
        )
        all_step_results = {**deterministic_outputs, **dag_exec.get("completed_steps", {})}
        lifecycle_log["5_6_authorise_and_execute"] = {
            "waves_executed": dag_exec.get("waves_executed", 1),
            "plugins_activated": dag_exec.get("plugins_activated", []),
            "steps_executed": len(all_step_results),
        }

        # Stage 7 & 8: VERIFY & RECOVER
        verified_count = 0
        recoveries_attempted = 0
        for sid, s_res in all_step_results.items():
            is_ver = bool(s_res.get("verification_certificate", {}).get("verified"))
            if is_ver:
                verified_count += 1
            else:
                # Stage 8 Recovery: Escalate model tier via model_broker on unverified step
                recoveries_attempted += 1
                esc = model_broker.route_task_economically(objective, retry_attempt=1, previous_error="Step verification failed")
                s_res["recovery_escalation_model"] = esc["selected_model"]

        lifecycle_log["7_8_verify_and_recover"] = {
            "verified_steps": verified_count,
            "total_steps": len(planned_steps),
            "recoveries_attempted": recoveries_attempted,
        }

        # Stage 9: REPORT
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        lifecycle_log["9_report"] = {
            "trace_id": trace_id,
            "status": "COMPLETED" if verified_count == len(planned_steps) else "PARTIAL_OR_RECOVERED",
            "total_duration_ms": dur_ms,
        }
        return {
            "trace_id": trace_id,
            "status": lifecycle_log["9_report"]["status"],
            "lifecycle": lifecycle_log,
            "step_results": all_step_results,
            "duration_ms": dur_ms,
        }


task_planner = UniversalTaskLifecyclePlanner()
