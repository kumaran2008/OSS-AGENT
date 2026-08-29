import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from models.schemas import RunLog, ModelCallLog


class RunLogger:
    """
    Writes one JSON file per run to logs/, plus appends a one-line
    summary to logs/history.jsonl for quick scanning across many runs.
    This is the foundation for later analysis: which models actually
    get used, cost trends, pass/fail rates over time.
    """

    def __init__(self, logs_dir: Path, dry_run: bool = False):
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log = RunLog(
            run_id=str(uuid.uuid4())[:8],
            started_at=datetime.now(timezone.utc).isoformat(),
            dry_run=dry_run,
        )

    def set_repo_issue(self, repo_full_name: str, issue_number: int, issue_title: str):
        self.log.repository = repo_full_name
        self.log.issue_number = issue_number
        self.log.issue_title = issue_title

    def note(self, message: str):
        self.log.notes.append(message)

    def set_outcome(self, outcome: str):
        self.log.outcome = outcome

    def set_test_result(self, passed: bool, retries_used: int):
        self.log.test_pass = passed
        self.log.debug_retries_used = retries_used

    def set_review_result(self, approved: bool):
        self.log.review_approved = approved

    def attach_model_calls(self, calls: list[ModelCallLog]):
        self.log.model_calls = calls

    def estimated_cost_summary(self) -> dict:
        total_prompt = sum(c.prompt_tokens for c in self.log.model_calls)
        total_completion = sum(c.completion_tokens for c in self.log.model_calls)
        by_model = {}
        for c in self.log.model_calls:
            by_model.setdefault(c.model_used, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
            by_model[c.model_used]["prompt_tokens"] += c.prompt_tokens
            by_model[c.model_used]["completion_tokens"] += c.completion_tokens
            by_model[c.model_used]["calls"] += 1
        return {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "by_model": by_model,
        }

    def finalize(self):
        self.log.finished_at = datetime.now(timezone.utc).isoformat()

        run_file = self.logs_dir / f"run-{self.log.run_id}.json"
        run_file.write_text(self.log.model_dump_json(indent=2))

        summary = {
            "run_id": self.log.run_id,
            "started_at": self.log.started_at,
            "finished_at": self.log.finished_at,
            "repository": self.log.repository,
            "issue_number": self.log.issue_number,
            "outcome": self.log.outcome,
            "dry_run": self.log.dry_run,
            "model_calls": len(self.log.model_calls),
            **self.estimated_cost_summary(),
        }
        history_file = self.logs_dir / "history.jsonl"
        with open(history_file, "a") as f:
            f.write(json.dumps(summary) + "\n")

        print(f"\n[RunLogger] Run log saved: {run_file}")
