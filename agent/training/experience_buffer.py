import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TrajectoryRecord:
    timestamp: float
    agent_role: str
    task_type: str
    input_context: str
    action_output: str
    outcome_reward: float  # 1.0 (passed/approved), 0.0 (fallback), -1.0 (syntax/compilation error)
    metadata: Dict[str, Any]


class ExperienceBuffer:
    """
    Append-only local trajectory storage for agent actions.
    Persists successful reasoning loops to enable offline QLoRA distillation.
    """

    def __init__(self, storage_dir: str = ".experience"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_buffer_path(self, agent_role: str) -> Path:
        clean_role = agent_role.lower().replace(" ", "_")
        return self.storage_dir / f"{clean_role}_trajectories.jsonl"

    def record_trajectory(
        self,
        agent_role: str,
        task_type: str,
        input_context: str,
        action_output: str,
        outcome_reward: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrajectoryRecord:
        """
        Appends an execution trajectory into the agent's dedicated JSONL buffer.
        """
        record = TrajectoryRecord(
            timestamp=time.time(),
            agent_role=agent_role,
            task_type=task_type,
            input_context=input_context,
            action_output=action_output,
            outcome_reward=outcome_reward,
            metadata=metadata or {},
        )

        buffer_file = self._get_buffer_path(agent_role)
        with open(buffer_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")

        return record

    def export_sft_dataset(self, agent_role: str, min_reward: float = 0.5) -> List[Dict[str, Any]]:
        """
        Exports successful trajectories into instruction-tuning conversation format.
        """
        buffer_file = self._get_buffer_path(agent_role)
        if not buffer_file.exists():
            return []

        dataset = []
        with open(buffer_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("outcome_reward", 0.0) >= min_reward:
                    dataset.append({
                        "messages": [
                            {"role": "user", "content": item["input_context"]},
                            {"role": "assistant", "content": item["action_output"]},
                        ],
                        "reward": item["outcome_reward"],
                        "task_type": item["task_type"],
                    })
        return dataset

    def get_stats(self) -> Dict[str, Any]:
        """Returns trajectory counts and average rewards by agent role."""
        stats = {}
        for file in self.storage_dir.glob("*_trajectories.jsonl"):
            role = file.stem.replace("_trajectories", "")
            count = 0
            rewards = []
            with open(file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
                        try:
                            rewards.append(json.loads(line).get("outcome_reward", 0.0))
                        except Exception:
                            pass
            avg_r = (sum(rewards) / len(rewards)) if rewards else 0.0
            stats[role] = {"samples": count, "average_reward": round(avg_r, 3)}
        return stats


# Global default buffer singleton
experience_buffer = ExperienceBuffer()
