from agent.memory.turn_retriever import turn_retriever
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class TaskLedgerState:
    task_slug: str
    objective: str
    status: str = "IN_PROGRESS"  # IN_PROGRESS | BLOCKED | COMPLETED
    invariants: List[str] = field(default_factory=list)
    failed_hypotheses: List[str] = field(default_factory=list)
    verified_assumptions: List[str] = field(default_factory=list)
    unconfirmed_hypotheses: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    completed_milestones: List[str] = field(default_factory=list)
    pending_milestones: List[str] = field(default_factory=list)
    window_id: int = 1
    last_updated: float = field(default_factory=time.time)


class PersistentCodexLedger:
    """Production-grade working memory engine with dual JSON/Markdown persistence."""

    def __init__(self, workspace_root: Optional[Union[str, Path]] = None, task_slug: str = "main"):
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        self.task_slug = task_slug
        self.codex_dir = self.workspace_root / ".codex"
        self.ledger_dir = self.codex_dir / "ledger"
        self.history_dir = self.codex_dir / "history"

        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        self.ledger_md_path = self.ledger_dir / f"{self.task_slug}-MEMORY.md"
        self.state_json_path = self.ledger_dir / f"{self.task_slug}-state.json"

        self.state = self._load_or_initialize()

    def _load_or_initialize(self) -> TaskLedgerState:
        """Loads state from disk if present; otherwise initializes a clean state."""
        if self.state_json_path.exists():
            try:
                with open(self.state_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                valid_keys = {field_name for field_name in TaskLedgerState.__dataclass_fields__}
                filtered_data = {k: v for k, v in data.items() if k in valid_keys}
                return TaskLedgerState(**filtered_data)
            except Exception:
                pass
        return TaskLedgerState(task_slug=self.task_slug, objective="")

    def _atomic_write(self, target_path: Path, content: str) -> None:
        """Writes to a temporary file and atomically replaces destination to prevent corruption."""
        temp_file = target_path.with_name(f"{target_path.name}.tmp_{os.getpid()}_{int(time.time()*1000)}")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
        temp_file.replace(target_path)

    def update_objective(self, objective: str):
        self.state.objective = objective
        self.sync_to_disk()

    def set_status(self, status: str):
        self.state.status = status
        self.sync_to_disk()

    def record_decision(self, invariant: str):
        """Records an architectural invariant or rule (e.g. 'Use Python standard library only')."""
        if invariant not in self.state.invariants:
            self.state.invariants.append(invariant)
            self.sync_to_disk()

    def record_failed_hypothesis(self, failure: str):
        """Records a failed patch or broken approach to prevent repetitive loops."""
        if failure not in self.state.failed_hypotheses:
            self.state.failed_hypotheses.append(failure)
            self.sync_to_disk()

    def record_verified_assumption(self, assumption: str):
        """Records a proven fact (e.g. 'FastAPI 0.110 running on port 8000')."""
        if assumption not in self.state.verified_assumptions:
            self.state.verified_assumptions.append(assumption)
            self.sync_to_disk()

    def mark_file_modified(self, filepath: Union[str, Path]):
        try:
            rel_path = os.path.relpath(filepath, self.workspace_root)
        except ValueError:
            rel_path = str(filepath)
        if rel_path not in self.state.modified_files:
            self.state.modified_files.append(rel_path)
            self.sync_to_disk()

    def complete_milestone(self, milestone: str):
        if milestone in self.state.pending_milestones:
            self.state.pending_milestones.remove(milestone)
        if milestone not in self.state.completed_milestones:
            self.state.completed_milestones.append(milestone)
        self.sync_to_disk()

    def add_pending_milestone(self, milestone: str):
        if milestone not in self.state.pending_milestones and milestone not in self.state.completed_milestones:
            self.state.pending_milestones.append(milestone)
            self.sync_to_disk()

    def archive_turn(self, tool_name: str, payload: str, result: str):
        """Appends tool and compiler outputs into an indexed history log with artifact spilling."""
        log_file = self.history_dir / f"window_{self.state.window_id}.jsonl"
        entry: Dict[str, Any] = {
            "timestamp": time.time(),
            "window_id": self.state.window_id,
            "tool": tool_name,
            "payload": payload,
            "result_summary": result[:1000] if len(result) > 1000 else result,
            "full_result_path": None,
        }

        # Spill large stdout/stderr payloads to dedicated artifact logs
        if len(result) > 2000:
            artifact_name = f"artifact_{int(time.time()*1000)}.log"
            artifact_path = self.history_dir / artifact_name
            with open(artifact_path, "w", encoding="utf-8") as af:
                af.write(result)
            entry["full_result_path"] = str(artifact_path)
            entry["result_summary"] = result[:300] + f"... [Truncated. Full output in {artifact_name}]"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        try:
            turn_retriever.index_turn(tool_name, payload, entry['result_summary'], self.state.window_id, entry.get('full_result_path'))
        except Exception:
            pass

    def turn_the_page(self) -> str:
        """Increments context window ID, flushes history, and emits Turn 0 rehydration prompt."""
        self.state.window_id += 1
        self.sync_to_disk()
        return self.render_rehydration_prompt()

    def sync_to_disk(self):
        """Atomically persists structured JSON and human-readable Markdown representations."""
        self.state.last_updated = time.time()
        self._atomic_write(self.state_json_path, json.dumps(asdict(self.state), indent=2))
        self._atomic_write(self.ledger_md_path, self._render_markdown())

    def _render_markdown(self) -> str:
        """Generates canonical Markdown ingested by LLM prompts."""
        return f"""# CODEX LEDGER: {self.task_slug.upper()}
> **Status**: {self.state.status} | **Active Window**: {self.state.window_id}

### Objective
{self.state.objective or "No objective set."}

### Architectural Invariants & Rules
{self._format_list(self.state.invariants, "- [INVARIANT]")}

### Discarded Approaches & Failed Fixes
{self._format_list(self.state.failed_hypotheses, "- [DO NOT REPEAT]")}

### Verification State
* **Confirmed Facts:**
{self._format_list(self.state.verified_assumptions, "  -")}
* **Unconfirmed Hypotheses:**
{self._format_list(self.state.unconfirmed_hypotheses, "  - [UNCONFIRMED]")}

### Milestones & Progress
{self._format_list(self.state.completed_milestones, "- [x]")}
{self._format_list(self.state.pending_milestones, "- [ ]")}

### Modified Artifacts
{self._format_list(self.state.modified_files, "- `") + ("`" if self.state.modified_files else "")}
"""

    def render_context_block(self, max_chars: int = 2500) -> str:
        """Renders an immutable, anti-amnesia context block for agent prompts."""
        md = self._render_markdown()
        return md if len(md) <= max_chars else md[:max_chars] + "\n...[Codex Ledger Truncated]"

    def render_rehydration_prompt(self) -> str:
        """Returns context string injected at the start of a rolled-over session."""
        return f"""[SYSTEM MEMORY RESTORATION]
You are resuming task: {self.task_slug}.
A context rollover occurred. Do not re-explore files already marked verified.

{self._render_markdown()}
Continue execution from the next pending milestone."""

    @staticmethod
    def _format_list(items: List[str], prefix: str) -> str:
        if not items:
            return "  *(None)*"
        return "\n".join(f"{prefix} {item}" for item in items)


# Default workspace singleton
codex_ledger = PersistentCodexLedger()
