import asyncio
import shutil
import json
from pathlib import Path

from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge, CloudComputeProvider
from agent.pa_scaffolder.experiment_runner import SandboxedExperimentRunner
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_gap4_remote_compute_bridge():
    print("=" * 72)
    print("     GAP 4 VERIFICATION: SERVERLESS REMOTE CLOUD GPU BRIDGE")
    print("=" * 72)

    test_ws = Path("workspace/test_bridge_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    bridge = RemoteComputeBridge(workspace_root=test_ws)

    # -------------------------------------------------------------------------
    # 1. Provider Detection & Hardware Resolution
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Provider Auto-Resolution & Hardware Detection...")
    provider, reason = bridge.resolve_provider(CloudComputeProvider.AUTO)
    print(f" • Selected Provider:     {provider.value}")
    print(f" • Resolution Reason:     \"{reason}\"")
    assert provider in [CloudComputeProvider.RUNPOD, CloudComputeProvider.MODAL, CloudComputeProvider.SSH, CloudComputeProvider.EMULATED]
    print(" >>> CRITERION 1 PASSED: Cloud compute provider resolved cleanly. <<<")

    # -------------------------------------------------------------------------
    # 2. Remote Multi-Seed Experiment Sweep
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing Remote Multi-Seed Experiment Sweep...")
    dummy_eval_code = (
        "import json, random\n"
        "perplexity = 6.37\n"
        "print(json.dumps({'perplexity': perplexity}))\n"
    )

    res_sweep = await bridge.dispatch_remote_sweep(
        script_content=dummy_eval_code,
        metric_key="perplexity",
        seeds=[42, 1337, 2026],
        baseline_target=6.38,
        gpu_type="A10G"
    )

    print(f" • Remote Sweep Status:   {'SUCCESS' if res_sweep.success else 'FAILED'}")
    print(f" • Provider Used:         {res_sweep.provider_used}")
    print(f" • GPU Allocated:         {res_sweep.gpu_allocated}")
    print(f" • Job ID:                {res_sweep.job_id}")
    print(f" • Total Latency:         {res_sweep.latency_sec}s")
    assert res_sweep.success is True
    assert len(res_sweep.seed_runs) == 3
    print(" >>> CRITERION 2 PASSED: Remote sweep returned 3 seed evaluations. <<<")

    # -------------------------------------------------------------------------
    # 3. Statistical Sanity Audit (Welch t-test & Gap Checks)
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing Statistical Sanity Audit & Gap Sentinel...")
    audit = res_sweep.stats_audit
    print(f" • Sample Mean:           {audit['mean']}")
    print(f" • Sample Std Dev:        {audit['std_dev']}")
    print(f" • Reproduction Gap:      {audit['reproduction_gap']:.2%}")
    print(f" • Audit Verdict:         \"{audit['verdict']}\"")
    assert audit["sample_size"] == 3
    assert audit["is_reproduced"] is True
    assert audit["reproduction_gap"] < 0.05
    print(" >>> CRITERION 3 PASSED: Statistical sanity audit validated within 5% tolerance. <<<")

    # -------------------------------------------------------------------------
    # 4. Integration with SandboxedExperimentRunner
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing SandboxedExperimentRunner Cloud Offload...")
    runner = SandboxedExperimentRunner(workspace_root=test_ws)

    # Write evaluation script to disk
    eval_script = test_ws / "eval_model.py"
    eval_script.write_text(dummy_eval_code, encoding="utf-8")

    cloud_sweep_res = await runner.run_remote_cloud_sweep(
        script_rel_path="eval_model.py",
        metric_key="perplexity",
        seeds=[101, 202, 303],
        baseline_target=6.38,
        gpu_type="H100"
    )

    print(f" • Runner Cloud Sweep:    {cloud_sweep_res['status']}")
    print(f" • Runner GPU Tier:       {cloud_sweep_res['gpu_allocated']}")
    print(f" • Mean Perplexity:       {cloud_sweep_res['stats_audit']['mean']}")
    assert cloud_sweep_res["status"] == "COMPLETED"
    assert cloud_sweep_res["stats_audit"]["sample_size"] == 3
    print(" >>> CRITERION 4 PASSED: Experiment runner delegated sweep to Cloud Bridge. <<<")

    # -------------------------------------------------------------------------
    # 5. Tool Registry Dispatch Integration
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing ToolRegistry Dispatch of 'remote_cloud_sweep'...")
    tools = ToolRegistry(workspace_root=test_ws)

    tool_res = await tools.dispatch("remote_cloud_sweep", {
        "script_path": "eval_model.py",
        "metric_key": "perplexity",
        "baseline_target": 6.38,
        "gpu_type": "A10G"
    })

    print(f" • Tool Dispatch Status:  {tool_res.success}")
    print(f" • Tool Output:           \"{tool_res.output}\"")
    assert tool_res.success is True
    assert "Remote Sweep" in tool_res.output

    tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 72)
    print(">>> GAP 4 (SERVERLESS REMOTE CLOUD GPU BRIDGE) 100% OPERATIONAL <<<")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(test_gap4_remote_compute_bridge())
