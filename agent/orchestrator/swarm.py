import os
import sys
import time
from typing import Dict, Any, List, Optional

from agent.memory.federated_ledger import SharedRootLedger
from agent.orchestrator.loop import AutonomousAgentLoop
from agent.orchestrator.queen_validator import QueenLedgerValidator

class SwarmOrchestrator:
    """
    Hardware-adaptive multi-agent coordinator (Queen).
    Spins up worker agents, manages turn execution, and validates all
    pull-requests through QueenLedgerValidator before merging to root.
    """
    def __init__(self, workspace_root: str, task_slug: str, token_ceiling: int = 4096):
        self.workspace_root = workspace_root
        self.task_slug = task_slug
        self.token_ceiling = token_ceiling
        
        # 1. Initialize root ledger and queen validator
        self.root_ledger = SharedRootLedger(workspace_root, task_slug)
        self.validator = QueenLedgerValidator(workspace_root, self.root_ledger)
        
        # 2. Worker registry
        self.workers: Dict[str, AutonomousAgentLoop] = {}

    def get_or_create_worker(self, role: str, base_instructions: str) -> AutonomousAgentLoop:
        agent_id = f"{role}_worker"
        if agent_id not in self.workers:
            self.workers[agent_id] = AutonomousAgentLoop(
                workspace_root=self.workspace_root,
                task_slug=self.task_slug,
                agent_id=agent_id,
                role=role,
                base_instructions=base_instructions,
                token_ceiling=self.token_ceiling
            )
        return self.workers[agent_id]

    def run_pipeline_step(
        self,
        role: str,
        instructions: str,
        simulated_actions: List[Dict[str, Any]],
        verified_facts: Optional[List[str]] = None
    ) -> bool:
        """
        Runs a worker agent, captures its staged delta, and passes it
        to QueenLedgerValidator. Returns True if approved and committed.
        """
        worker_loop = self.get_or_create_worker(role, instructions)
        worker_scratchpad = worker_loop.worker

        print(f"\n[SWARM] Activating subagent: {role.upper()} ({worker_scratchpad.agent_id})")
        for turn_idx, action in enumerate(simulated_actions):
            res = worker_loop.run_turn(action)
            print(f"  [Turn {turn_idx + 1}] {res}")

        # Construct pending delta payload from worker scratchpad
        staged_delta = {
            "candidate_invariants": list(worker_scratchpad.data.candidate_invariants),
            "resolved_milestones": list(worker_scratchpad.data.resolved_milestones),
            "pending_milestones": list(worker_scratchpad.data.pending_milestones),
            "files_touched": list(worker_scratchpad.data.files_touched),
            "verified_facts": verified_facts or []
        }

        # Queen reviews and commits or rejects
        approved, report = self.validator.review_and_commit(
            agent_id=worker_scratchpad.agent_id,
            role=role,
            worker_delta=staged_delta
        )
        print(f"[SWARM-QUEEN] {report}")

        if approved:
            # Clear local staged items upon successful root commit
            worker_scratchpad.data.candidate_invariants.clear()
            worker_scratchpad.data.resolved_milestones.clear()
            worker_scratchpad.data.files_touched.clear()
            worker_scratchpad._sync_disk()
            return True
        else:
            print(f"[SWARM-QUEEN] Worker {role} must rectify validation errors before state can merge.")
            return False
