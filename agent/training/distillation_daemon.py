import json
import time
from pathlib import Path
from typing import Any, Dict, List
from tools.system_tier import CURRENT_TIER
from agent.training.dataset_compiler import TrajectoryDatasetCompiler
from agent.training.experience_buffer import experience_buffer
from agent.training.qlora_pipeline import QLoRAPipeline, get_tier_label
from agent.training.safety_gate import SelfEvaluationGate
from agent.training.adapter_registry import adapter_registry


class DistillationDaemon:
    """
    Offline autonomous training manager.
    Compiles datasets from .experience/ buffers, manages QLoRA staging/dispatch,
    evaluates adapters against safety regression benchmarks, and maintains the adapter registry.
    """

    def __init__(self, min_samples_threshold: int = 1):
        self.min_samples_threshold = min_samples_threshold
        self.compiler = TrajectoryDatasetCompiler()
        self.qlora = QLoRAPipeline()
        self.safety_gate = SelfEvaluationGate()

    def check_eligibility(self) -> Dict[str, Dict[str, Any]]:
        stats = experience_buffer.get_stats()
        manifest = {}
        for role, data in stats.items():
            samples = data.get("samples", 0)
            avg_reward = data.get("average_reward", 0.0)
            eligible = (samples >= self.min_samples_threshold) and (avg_reward >= 0.7)
            manifest[role] = {
                "samples": samples,
                "average_reward": avg_reward,
                "eligible": eligible,
            }
        return manifest

    def should_trigger_training(self) -> Dict[str, bool]:
        eligibility = self.check_eligibility()
        return {role: info["eligible"] for role, info in eligibility.items()}

    def run_training_cycle(self) -> Dict[str, Any]:
        eligibility = self.check_eligibility()
        tier_name = get_tier_label()
        summary: Dict[str, Any] = {
            "timestamp": time.time(),
            "tier": tier_name,
            "processed_roles": {},
            "staged_exports": [],
            "trained_roles": [],
        }

        print("\n=== [Distillation Daemon] Initiating Offline Training Cycle ===")
        for role, info in eligibility.items():
            if not info["eligible"]:
                print(f"  • {role}: Skipped (Samples: {info['samples']}, Avg Reward: {info['average_reward']})")
                continue

            print(f"\n[Distillation Daemon] Processing role '{role}'...")

            # 1. Compile SFT Dataset
            dataset_path = self.compiler.compile_role_dataset(role, min_reward=0.7)

            # 2. Safety Gate Pre-Check
            bench_results = self.safety_gate.run_benchmark_suite()
            if not bench_results["passed"]:
                print(f"[Distillation Daemon] Safety gate rejected '{role}'.")
                summary["processed_roles"][role] = {
                    "status": "REJECTED_BY_SAFETY_GATE",
                    "benchmark": bench_results,
                }
                continue

            # 3. Dispatch or Stage QLoRA
            job_result = self.qlora.dispatch_training_job(role, dataset_path)

            # 4. Register in Central Manifest
            reg_entry = adapter_registry.register_adapter(
                role=role,
                adapter_path=job_result.get("adapter_dir", str(dataset_path.parent)),
                base_model=self.qlora.DEFAULT_BASE_MODEL,
                benchmark_score=bench_results["pass_rate"],
                training_samples=info["samples"],
                metadata={"job_status": job_result["status"], "tier": tier_name},
            )

            summary["processed_roles"][role] = {
                "job": job_result,
                "registered": reg_entry,
            }

            if job_result["status"] == "COMPLETED":
                summary["trained_roles"].append(job_result)
            else:
                summary["staged_exports"].append(job_result)

            print(f"[Distillation Daemon] Role '{role}' complete -> Status: {job_result['status']}")

        print("\n=== [Distillation Daemon] Cycle Complete ===")
        return summary

    def execute_distillation_cycle(self) -> Dict[str, Any]:
        return self.run_training_cycle()


distillation_daemon = DistillationDaemon()
