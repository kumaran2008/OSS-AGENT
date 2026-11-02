import json
from pathlib import Path
from typing import Any, Dict, List
from agent.training.experience_buffer import experience_buffer


class TrajectoryDatasetCompiler:
    """
    Transforms raw agent experience trajectories into standardized ChatML/ShareGPT
    instruction-tuning datasets for QLoRA and SFT distillation.
    """

    SYSTEM_PROMPTS = {
        "tester": "You are a master QA and diagnostic engineer specializing in root-cause isolation and automated patching.",
        "reviewer": "You are an adversarial diff auditor enforcing code safety, zero unconstrained churn, and clean commits.",
        "mason_backend_mason": "You are an expert backend software architect specializing in performant and clean APIs.",
        "mason_frontend_mason": "You are an expert frontend engineer specializing in responsive, modern web interfaces.",
        "mason_config_mason": "You are a systems infrastructure engineer specialized in packaging, CI/CD, and configurations.",
    }

    def __init__(self, output_dir: str = ".experience/datasets"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile_role_dataset(self, role: str, min_reward: float = 0.8) -> Path:
        """
        Compiles all trajectories meeting the reward threshold for a given role into a JSONL dataset.
        """
        records = experience_buffer.export_sft_dataset(role, min_reward=min_reward)
        output_file = self.output_dir / f"{role}_sft.jsonl"
        system_msg = self.SYSTEM_PROMPTS.get(
            role, "You are a specialized autonomous engineering agent."
        )

        compiled_count = 0
        with open(output_file, "w", encoding="utf-8") as f:
            for item in records:
                formatted_conversation = {
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": item["messages"][0]["content"]},
                        {"role": "assistant", "content": item["messages"][1]["content"]},
                    ],
                    "metadata": {
                        "reward": item.get("reward", 1.0),
                        "task_type": item.get("task_type", "general"),
                    },
                }
                f.write(json.dumps(formatted_conversation) + "\n")
                compiled_count += 1

        print(f"[DatasetCompiler] Exported {compiled_count} samples for role '{role}' -> {output_file}")
        return output_file

    def compile_all_active(self, min_reward: float = 0.8) -> Dict[str, Path]:
        """Compiles datasets for all agents that have recorded trajectory data."""
        stats = experience_buffer.get_stats()
        manifest = {}
        for role, data in stats.items():
            if data["samples"] > 0 and data["average_reward"] >= min_reward:
                manifest[role] = self.compile_role_dataset(role, min_reward=min_reward)
        return manifest
