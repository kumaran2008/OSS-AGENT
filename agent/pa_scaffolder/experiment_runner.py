from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge, CloudComputeProvider
import os
import sys
import re
import time
import json
import uuid
import shutil
import asyncio
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple, Union

from agent.pa_scaffolder.research_memory import ResearchMemoryLayer, ExperimentRecord
from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier, StatisticalAuditReport


@dataclass
class SweepRunResult:
    experiment_id: str
    paper_id: Optional[str]
    name: str
    seeds_tested: List[int]
    metric_name: str
    reproduced_values: List[float]
    baseline_target: Optional[float]
    stats_audit: StatisticalAuditReport
    execution_time_sec: float
    auto_healed_dependencies: List[str]
    report_md: str


class SandboxedExperimentRunner:
    """
    Sandboxed Multi-Seed Experiment Orchestrator:
    - Runs Python experiment scripts across multiple random seeds (N ≥ 3).
    - Detects and auto-installs missing dependencies (pip).
    - Collects structured stdout metrics (`METRIC: {"loss": 0.42}`).
    - Executes statistical audit and logs permanently to SQLite WAL memory.
    """

    def __init__(
        self,
        arg1: Any = None,
        arg2: Any = None,
        arg3: Any = None,
        *,
        memory: Optional[Any] = None,
        verifier: Optional[Any] = None,
        workspace_root: Optional[Union[str, Path]] = None
    ):
        resolved_ws = workspace_root
        resolved_mem = memory
        resolved_ver = verifier
        
        positionals = [a for a in (arg1, arg2, arg3) if a is not None]
        for item in positionals:
            if isinstance(item, (str, Path)) and resolved_ws is None:
                resolved_ws = item
            elif hasattr(item, "store_paper") or hasattr(item, "record_dead_end") or "Memory" in type(item).__name__:
                if resolved_mem is None:
                    resolved_mem = item
            elif hasattr(item, "verify_mathematical_derivation") or hasattr(item, "audit_experimental_seeds") or "Verifier" in type(item).__name__:
                if resolved_ver is None:
                    resolved_ver = item
            elif resolved_ws is None and not hasattr(item, "store_paper") and not hasattr(item, "verify_mathematical_derivation"):
                resolved_ws = item
        
        self.workspace_root = Path(resolved_ws or ".").resolve()
        if resolved_mem is None:
            from agent.pa_scaffolder.research_memory import ResearchMemoryLayer
            self.memory = ResearchMemoryLayer(db_path=self.workspace_root / "vault.db")
        else:
            self.memory = resolved_mem
        
        if resolved_ver is None:
            from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier
            self.verifier = MathAndStatsVerifier()
        else:
            self.verifier = resolved_ver
        
        self.remote_bridge = RemoteComputeBridge(self.workspace_root)

    def detect_missing_dependency(self, stderr_output: str) -> Optional[str]:
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", stderr_output)
        if match:
            return match.group(1)
        return None

    def auto_heal_dependency(self, module_name: str) -> Tuple[bool, str]:
        cmd = [sys.executable, "-m", "pip", "install", module_name]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120.0)
        return (res.returncode == 0), res.stdout.strip()

    async def execute_multi_seed_sweep(
        self,
        script_relative_path: str,
        metric_key: str,
        seeds: Optional[List[int]] = None,
        baseline_target: Optional[float] = None,
        paper_id: Optional[str] = None,
        name: str = "Empirical Reproduction Sweep",
        timeout_per_run: float = 30.0
    ) -> SweepRunResult:
        """
        Executes paper code across random seeds, extracting structured metrics
        and auditing results against baseline.
        """
        run_seeds = seeds or [42, 1337, 2026]
        full_script_path = (self.workspace / script_relative_path).resolve()
        experiment_id = f"exp_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        reproduced_metrics: List[float] = []
        healed_deps: List[str] = []
        t0 = time.monotonic()

        for seed in run_seeds:
            cmd = f"python {script_relative_path} --seed {seed}"
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["EXPERIMENT_SEED"] = str(seed)

            # Execute run in subprocess executor
            loop = asyncio.get_running_loop()
            def _run():
                return subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(self.workspace),
                    capture_output=True,
                    text=True,
                    timeout=timeout_per_run,
                    env=env
                )

            res = await loop.run_in_executor(None, _run)

            # Auto-Dependency Healing Interceptor
            if res.returncode != 0:
                missing = self.detect_missing_dependency(res.stderr)
                if missing and missing not in healed_deps:
                    ok_heal, _ = self.auto_heal_dependency(missing)
                    if ok_heal:
                        healed_deps.append(missing)
                        # Re-run after dependency install
                        res = await loop.run_in_executor(None, _run)

            # Parse Metric from stdout
            # Expected format: {"loss": 0.42, "accuracy": 94.1} or METRIC: {"perplexity": 6.38}
            parsed_metric = None
            for line in res.stdout.splitlines():
                if "{" in line and "}" in line:
                    try:
                        json_str = line[line.find("{"):line.rfind("}")+1]
                        data = json.loads(json_str)
                        if metric_key in data:
                            parsed_metric = float(data[metric_key])
                            break
                    except Exception:
                        continue

            if parsed_metric is not None:
                reproduced_metrics.append(parsed_metric)

                # Ledger individual seed run to SQLite WAL
                self.memory.record_experiment(ExperimentRecord(
                    experiment_id=f"{experiment_id}_s{seed}",
                    paper_id=paper_id,
                    name=f"{name} (Seed {seed})",
                    hypothesis=f"Reproducing {metric_key} ≈ {baseline_target}",
                    commit_hash="local_head",
                    seed=seed,
                    config={"seed": seed, "metric": metric_key},
                    metrics={metric_key: parsed_metric},
                    status="reproduced" if baseline_target and abs(parsed_metric - baseline_target)/baseline_target < 0.05 else "completed",
                    reproduction_gap=round(abs(parsed_metric - baseline_target)/baseline_target, 4) if baseline_target else 0.0
                ))

        total_time = time.monotonic() - t0

        # Run Statistical Sanity Audit
        stats = self.verifier.audit_reproduced_metrics(reproduced_metrics, baseline_target)

        # Build Markdown Audit Report
        report_lines = [
            f"# EXPERIMENTAL REPRODUCTION AUDIT: {name.upper()}",
            f"• Target Paper: {paper_id or 'Local Specification'}",
            f"• Tested Seeds: {run_seeds} | Successful Runs: {len(reproduced_metrics)}/{len(run_seeds)}",
            f"• Target Metric: `{metric_key}` = {baseline_target if baseline_target is not None else 'N/A'}",
            f"• Empirical Mean: **{stats.mean:.4f}** (± {stats.std_dev:.4f})",
            f"• 95% Confidence Interval: [{stats.ci_95_lower:.4f}, {stats.ci_95_upper:.4f}]",
            f"• Reproduction Gap: **{stats.reproduction_gap:.2%}**",
            f"• Verdict: **{stats.verdict}**",
            ""
        ]
        if stats.flags:
            report_lines.append("## ⚠️ STATISTICAL & INTEGRITY FLAGS:")
            for fl in stats.flags:
                report_lines.append(f"  • {fl}")
        if healed_deps:
            report_lines.append(f"\n## 🛠️ Auto-Healed Dependencies: {', '.join(healed_deps)}")

        # Ledger aggregated experiment record
        self.memory.record_experiment(ExperimentRecord(
            experiment_id=experiment_id,
            paper_id=paper_id,
            name=name,
            hypothesis=f"Multi-seed reproduction of {metric_key}",
            commit_hash="local_head",
            seed=0,
            config={"seeds": run_seeds, "metric": metric_key},
            metrics={"mean": stats.mean, "std_dev": stats.std_dev, "values": reproduced_metrics},
            status="reproduced" if "REPRODUCED" in stats.verdict else "diverged",
            reproduction_gap=stats.reproduction_gap
        ))

        return SweepRunResult(
            experiment_id=experiment_id,
            paper_id=paper_id,
            name=name,
            seeds_tested=run_seeds,
            metric_name=metric_key,
            reproduced_values=reproduced_metrics,
            baseline_target=baseline_target,
            stats_audit=stats,
            execution_time_sec=round(total_time, 2),
            auto_healed_dependencies=healed_deps,
            report_md="\n".join(report_lines)
        )

    async def run_remote_cloud_sweep(
        self,
        script_rel_path: str,
        metric_key: str,
        seeds: List[int],
        baseline_target: Optional[float] = None,
        gpu_type: str = "A10G",
        name: str = "Remote Cloud Sweep"
    ) -> Dict[str, Any]:
        """Executes experiment sweep on remote cloud GPU via RemoteComputeBridge."""
        target_path = self.workspace_root / script_rel_path
        script_code = target_path.read_text(encoding="utf-8") if target_path.exists() else ""

        res = await self.remote_bridge.dispatch_remote_sweep(
            script_content=script_code,
            metric_key=metric_key,
            seeds=seeds,
            baseline_target=baseline_target,
            gpu_type=gpu_type
        )

        return {
            "name": name,
            "status": "COMPLETED" if res.success else "FAILED",
            "provider": res.provider_used,
            "gpu_allocated": res.gpu_allocated,
            "job_id": res.job_id,
            "runs": res.seed_runs,
            "stats_audit": res.stats_audit,
            "latency_sec": res.latency_sec,
            "cost_estimate_usd": res.cost_estimate_usd
        }
