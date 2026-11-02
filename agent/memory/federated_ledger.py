import os
import sys
import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

try:
    from agent.hardware.runtime_adapter import detect_hardware_tier, RuntimeTier
except ImportError:
    class RuntimeTier:
        LOW_SPEC_MOBILE = "low_spec_mobile"
        MID_SPEC = "mid_spec"
        HIGH_SPEC = "high_spec"

    def detect_hardware_tier():
        is_android = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ
        return RuntimeTier.LOW_SPEC_MOBILE if is_android else RuntimeTier.MID_SPEC

from agent.memory.conflict_resolver import AdaptiveConflictResolver


class AdaptiveFileLock:
    def __init__(self, lock_path: Path, timeout: float = 10.0, poll_interval: float = 0.05):
        self.lock_path = lock_path
        self.dir_lock_path = lock_path.with_suffix(".dirlock")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd = None
        self._use_kernel_lock = True
        
        if "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ or sys.platform == "win32":
            self._use_kernel_lock = False

    def __enter__(self):
        start = time.time()
        while True:
            if self._use_kernel_lock:
                try:
                    import fcntl
                    self._fd = open(self.lock_path, "w")
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except (IOError, OSError, ImportError):
                    self._use_kernel_lock = False
                    if self._fd:
                        try:
                            self._fd.close()
                        except Exception:
                            pass
                        self._fd = None

            try:
                os.mkdir(self.dir_lock_path)
                return self
            except FileExistsError:
                pass

            if time.time() - start > self.timeout:
                raise TimeoutError(f"Deadlock timeout for {self.lock_path}")
            time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._use_kernel_lock and self._fd:
            try:
                import fcntl
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
        else:
            try:
                os.rmdir(self.dir_lock_path)
            except OSError:
                pass


@dataclass
class ScratchpadMemory:
    agent_id: str
    active_role: str
    hypotheses: List[str] = field(default_factory=list)
    local_notes: List[str] = field(default_factory=list)
    candidate_invariants: List[str] = field(default_factory=list)
    resolved_milestones: List[str] = field(default_factory=list)
    pending_milestones: List[str] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)


@dataclass
class SharedRootLedgerState:
    task_slug: str
    global_objective: str
    invariants: List[str] = field(default_factory=list)
    invariant_authors: Dict[str, str] = field(default_factory=dict)       # invariant -> role
    completed_milestones: List[str] = field(default_factory=list)
    pending_milestones: List[str] = field(default_factory=list)
    milestone_authors: Dict[str, str] = field(default_factory=dict)       # milestone -> role
    modified_artifacts: List[str] = field(default_factory=list)
    verified_facts: List[str] = field(default_factory=list)
    active_workers: Dict[str, str] = field(default_factory=dict)
    revision: int = 0
    last_synced: float = field(default_factory=time.time)


class SharedRootLedger:
    def __init__(self, workspace_root: str, task_slug: str):
        self.workspace = Path(workspace_root)
        self.task_slug = task_slug
        self.ledger_dir = self.workspace / ".codex" / "ledger"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_file = self.ledger_dir / f"{task_slug}-root.json"
        self.md_file = self.ledger_dir / f"{task_slug}-ROOT.md"
        self.lock_file = self.ledger_dir / f"{task_slug}.lock"
        self.resolver = AdaptiveConflictResolver()
        
        self._init_or_load()

    def _init_or_load(self):
        with AdaptiveFileLock(self.lock_file):
            if not self.state_file.exists():
                initial = SharedRootLedgerState(
                    task_slug=self.task_slug,
                    global_objective="Define global task parameters"
                )
                self._save_state_unlocked(initial)

    def _load_state_unlocked(self) -> SharedRootLedgerState:
        with open(self.state_file, "r", encoding="utf-8") as f:
            return SharedRootLedgerState(**json.load(f))

    def _save_state_unlocked(self, state: SharedRootLedgerState):
        state.revision += 1
        state.last_synced = time.time()
        
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)

        md = f"""# ROOT LEDGER: {state.task_slug.upper()} (Rev: {state.revision})
**Objective**: {state.global_objective}

### Universal Invariants
"""
        for inv in state.invariants:
            author = state.invariant_authors.get(inv, "system")
            md += f"- [INVARIANT] {inv} *(author: {author})*\n"

        md += f"\n### Global Milestones\n"
        for cm in state.completed_milestones:
            md += f"- [x] {cm}\n"
        for pm in state.pending_milestones:
            md += f"- [ ] {pm}\n"

        md += f"\n### Modified Artifacts\n"
        for fpath in state.modified_artifacts:
            md += f"- `{fpath}`\n"

        with open(self.md_file, "w", encoding="utf-8") as f:
            f.write(md)

    def register_worker(self, agent_id: str, role: str):
        with AdaptiveFileLock(self.lock_file):
            st = self._load_state_unlocked()
            st.active_workers[agent_id] = role
            self._save_state_unlocked(st)

    def commit_worker_delta(self, role: str, delta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hardware-adaptive conflict resolution merge.
        Returns a dict of accepted deltas and rejection reasons.
        """
        with AdaptiveFileLock(self.lock_file):
            st = self._load_state_unlocked()
            merge_report = {"accepted_invariants": [], "rejected_invariants": [], "rejected_milestones": []}

            # 1. Arbitrate Invariants
            candidate_invs = delta.get("candidate_invariants", [])
            accepted_invs, rejected_invs = self.resolver.arbitrate_invariants(
                worker_role=role,
                candidates=candidate_invs,
                existing_invariants=st.invariants,
                invariant_authors=st.invariant_authors
            )
            for inv in accepted_invs:
                if inv not in st.invariants:
                    st.invariants.append(inv)
                st.invariant_authors[inv] = role
                merge_report["accepted_invariants"].append(inv)
            merge_report["rejected_invariants"] = rejected_invs

            # 2. Arbitrate Milestones
            for done in delta.get("resolved_milestones", []):
                ok, reason = self.resolver.resolve_milestone_transition(
                    worker_role=role,
                    milestone=done,
                    action="complete",
                    completed_in_root=st.completed_milestones,
                    pending_in_root=st.pending_milestones,
                    root_milestone_authors=st.milestone_authors
                )
                if ok:
                    if done in st.pending_milestones:
                        st.pending_milestones.remove(done)
                    if done not in st.completed_milestones:
                        st.completed_milestones.append(done)
                    st.milestone_authors[done] = role
                else:
                    merge_report["rejected_milestones"].append((done, reason))

            for pending in delta.get("pending_milestones", []):
                ok, reason = self.resolver.resolve_milestone_transition(
                    worker_role=role,
                    milestone=pending,
                    action="add",
                    completed_in_root=st.completed_milestones,
                    pending_in_root=st.pending_milestones,
                    root_milestone_authors=st.milestone_authors
                )
                if ok:
                    if pending not in st.pending_milestones and pending not in st.completed_milestones:
                        st.pending_milestones.append(pending)
                        st.milestone_authors[pending] = role
                else:
                    merge_report["rejected_milestones"].append((pending, reason))

            # 3. Merge Artifacts & Facts
            for path in delta.get("files_touched", []):
                if path not in st.modified_artifacts:
                    st.modified_artifacts.append(path)

            for fact in delta.get("verified_facts", []):
                if fact not in st.verified_facts:
                    st.verified_facts.append(fact)

            self._save_state_unlocked(st)
            return merge_report

    def get_read_only_view(self) -> SharedRootLedgerState:
        with AdaptiveFileLock(self.lock_file):
            return self._load_state_unlocked()


class WorkerAgentScratchpad:
    def __init__(self, root_ledger: SharedRootLedger, agent_id: str, role: str):
        self.root = root_ledger
        self.agent_id = agent_id
        self.role = role
        self.tier = detect_hardware_tier()
        
        self.scratchpad_dir = self.root.ledger_dir / "scratchpads"
        self.scratchpad_dir.mkdir(parents=True, exist_ok=True)
        self.local_file = self.scratchpad_dir / f"{self.agent_id}.json"
        
        self.data = ScratchpadMemory(agent_id=self.agent_id, active_role=self.role)
        self.root.register_worker(self.agent_id, self.role)
        self._sync_disk()

    def record_hypothesis(self, text: str):
        if text not in self.data.hypotheses:
            self.data.hypotheses.append(text)
            self._sync_disk()

    def touch_file(self, path: str):
        if path not in self.data.files_touched:
            self.data.files_touched.append(path)
            self._sync_disk()

    def propose_invariant(self, invariant: str):
        if invariant not in self.data.candidate_invariants:
            self.data.candidate_invariants.append(invariant)
            self._sync_disk()

    def complete_subtask(self, milestone: str):
        if milestone not in self.data.resolved_milestones:
            self.data.resolved_milestones.append(milestone)
            self._sync_disk()

    def sync_to_root(self, verified_facts: Optional[List[str]] = None) -> Dict[str, Any]:
        delta = {
            "candidate_invariants": self.data.candidate_invariants,
            "resolved_milestones": self.data.resolved_milestones,
            "pending_milestones": self.data.pending_milestones,
            "files_touched": self.data.files_touched,
            "verified_facts": verified_facts or []
        }
        
        report = self.root.commit_worker_delta(role=self.role, delta=delta)
        self.data.candidate_invariants.clear()
        self.data.resolved_milestones.clear()
        self.data.files_touched.clear()
        self._sync_disk()
        return report

    def build_context_prompt(self) -> str:
        root_state = self.root.get_read_only_view()
        if self.tier == RuntimeTier.LOW_SPEC_MOBILE:
            return (
                f"[LEDGER: {self.role.upper()} ({self.agent_id})]\n"
                f"ROOT INVARIANTS: {'; '.join(root_state.invariants) or 'None'}\n"
                f"FACTS: {'; '.join(root_state.verified_facts) or 'None'}\n"
                f"PENDING MILESTONES: {'; '.join(root_state.pending_milestones) or 'None'}\n"
            )
        else:
            invariants_fmt = "\n".join(f"- {i}" for i in root_state.invariants) or "  *(None)*"
            facts_fmt = "\n".join(f"- {f}" for f in root_state.verified_facts) or "  *(None)*"
            return f"""# SYSTEM CONTEXT [Role: {self.role.upper()} | Agent: {self.agent_id}]
## Shared Universal Invariants
{invariants_fmt}

## Confirmed Facts
{facts_fmt}

## Private Scratchpad
- Hypotheses: {self.data.hypotheses}
- Staged Invariants: {self.data.candidate_invariants}
"""

    def _sync_disk(self):
        with open(self.local_file, "w", encoding="utf-8") as f:
            json.dump(asdict(self.data), f, indent=2 if self.tier != RuntimeTier.LOW_SPEC_MOBILE else None)
