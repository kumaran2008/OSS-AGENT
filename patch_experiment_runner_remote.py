from pathlib import Path

target = Path("agent/pa_scaffolder/experiment_runner.py")
code = target.read_text(encoding="utf-8")

# 1. Add RemoteComputeBridge import
if "from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge" not in code:
    code = "from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge, CloudComputeProvider\n" + code

# 2. Add bridge attribute to SandboxedExperimentRunner.__init__
old_init = "self.workspace_root = (workspace_root or Path(\".\")).resolve()"
new_init = old_init + "\n        self.remote_bridge = RemoteComputeBridge(self.workspace_root)"

if old_init in code and "self.remote_bridge =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add remote sweep dispatch method
remote_method = """    async def run_remote_cloud_sweep(
        self,
        script_rel_path: str,
        metric_key: str,
        seeds: List[int],
        baseline_target: Optional[float] = None,
        gpu_type: str = "A10G",
        name: str = "Remote Cloud Sweep"
    ) -> Dict[str, Any]:
        \"\"\"Executes experiment sweep on remote cloud GPU via RemoteComputeBridge.\"\"\"
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
"""

if "def run_remote_cloud_sweep" not in code:
    code = code + "\n" + remote_method

target.write_text(code, encoding="utf-8")
print("[✓] Integrated RemoteComputeBridge into experiment_runner.py.")
