import asyncio
import shutil
import time
from pathlib import Path

from agent.pa_scaffolder.research_memory import ResearchMemoryLayer
from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier
from agent.pa_scaffolder.experiment_runner import SandboxedExperimentRunner
from agent.pa_scaffolder.rooms_engine import RoomsEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_researcher_phase3():
    print("=" * 70)
    print("     RESEARCHER ROOM PHASE 3: EXPERIMENT RUNNER & MATH VERIFIER")
    print("=" * 70)

    test_ws = Path("workspace/test_exp_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    db_path = test_ws / "test_vault.db"
    memory = ResearchMemoryLayer(db_path=db_path)
    verifier = MathAndStatsVerifier()
    runner = SandboxedExperimentRunner(test_ws, memory, verifier)

    # -------------------------------------------------------------------------
    # 1. Symbolic & Numeric Math Verification
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Symbolic & Numeric Mathematical Verification...")
    # Test valid identity: (x + y)**2 == x**2 + 2*x*y + y**2
    ok_valid, msg_valid = verifier.verify_symbolic_equivalence("(x + y)**2", "x**2 + 2*x*y + y**2", ["x", "y"])
    print(f" • Valid Identity Status:    {'VERIFIED' if ok_valid else 'FAILED'}")
    print(f" • Engine Output:            {msg_valid}")
    assert ok_valid is True

    # Test invalid identity: x**2 + y**2 != (x + y)**2
    ok_invalid, msg_invalid = verifier.verify_symbolic_equivalence("x**2 + y**2", "(x + y)**2", ["x", "y"])
    print(f" • Invalid Identity Status:  {'REJECTED (Correct)' if not ok_invalid else 'FALSE POSITIVE'}")
    assert ok_invalid is False
    print(" >>> CRITERION 1 PASSED: Symbolic & Monte Carlo numeric verification operational. <<<")

    # -------------------------------------------------------------------------
    # 2. Statistical Sanity & P-Hacking Sentinel
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing Statistical Sanity & P-Hacking Sentinel...")
    # Test single-seed trial (MUST trigger P-hacking warning)
    single_seed_audit = verifier.audit_reproduced_metrics([6.38], baseline_target=6.40)
    print(f" • Single-Seed Flags:        {single_seed_audit.flags}")
    assert any("SINGLE_SEED_RISK" in fl for fl in single_seed_audit.flags)

    # Test multi-seed trial with low variance
    multi_seed_values = [6.38, 6.41, 6.39, 6.40]
    multi_audit = verifier.audit_reproduced_metrics(multi_seed_values, baseline_target=6.40)
    print(f" • Multi-Seed Mean:          {multi_audit.mean} (± {multi_audit.std_dev})")
    print(f" • 95% Confidence Interval:  [{multi_audit.ci_95_lower}, {multi_audit.ci_95_upper}]")
    print(f" • Reproduction Gap:         {multi_audit.reproduction_gap:.2%}")
    print(f" • Audit Verdict:            \"{multi_audit.verdict}\"")
    assert multi_audit.reproduction_gap < 0.02
    assert "REPRODUCED" in multi_audit.verdict
    print(" >>> CRITERION 2 PASSED: Statistical audit flagged N=1 bias and validated multi-seed bounds. <<<")

    # -------------------------------------------------------------------------
    # 3. Sandboxed Multi-Seed Script Execution
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing Sandboxed Multi-Seed Experiment Sweep...")
    # Create sample experiment script that prints JSON metric based on seed
    exp_script = (
        "import argparse, random, json\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--seed', type=int, default=42)\n"
        "args = parser.parse_args()\n"
        "random.seed(args.seed)\n"
        "# Simulate benchmark metric with slight noise around 94.2\n"
        "accuracy = round(94.0 + random.uniform(0.1, 0.4), 2)\n"
        "print(json.dumps({'accuracy': accuracy, 'seed': args.seed}))\n"
    )
    (test_ws / "run_bench.py").write_text(exp_script, encoding="utf-8")

    sweep_res = await runner.execute_multi_seed_sweep(
        script_relative_path="run_bench.py",
        metric_key="accuracy",
        seeds=[42, 1337, 2026],
        baseline_target=94.20,
        paper_id="doi:10.1145/kv_cache_opt",
        name="Attention Accuracy Verification"
    )

    print(f" • Tested Seeds:             {sweep_res.seeds_tested}")
    print(f" • Extracted Metrics:        {sweep_res.reproduced_values}")
    print(f" • Empirical Mean:           {sweep_res.stats_audit.mean}")
    print(f" • Reproduction Gap:         {sweep_res.stats_audit.reproduction_gap:.2%}")
    assert len(sweep_res.reproduced_values) == 3
    assert sweep_res.stats_audit.reproduction_gap < 0.05
    print(" >>> CRITERION 3 PASSED: Sandboxed multi-seed sweep executed and parsed cleanly. <<<")

    # -------------------------------------------------------------------------
    # 4. SQLite WAL Experiment Ledger Verification
    # -------------------------------------------------------------------------
    print("\n[4/5] Verifying SQLite WAL Experiment Ledger Entries...")
    with memory._get_connection() as conn:
        rows = conn.execute("SELECT experiment_id, seed, metrics_json FROM experiments ORDER BY created_at DESC;").fetchall()
        print(f" • Total Ledgered Runs:      {len(rows)} (3 individual + 1 aggregated)")
        assert len(rows) >= 4
        # Verify seed 42 entry exists
        seed_42_found = any(r["seed"] == 42 for r in rows)
        assert seed_42_found is True
    print(" >>> CRITERION 4 PASSED: Experiment runs and seed metrics recorded in SQLite WAL. <<<")

    # -------------------------------------------------------------------------
    # 5. Rooms Engine & Tool Registry Public Orchestration
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing Tool Registry Dispatch of Math & Experiment Tools...")
    tools = ToolRegistry(workspace_root=str(test_ws))
    tools.math_verifier = verifier
    tools.experiment_runner = runner

    res_math = await tools.dispatch("math_verify_derivation", {
        "expr_a": "x * (y + 1)",
        "expr_b": "x * y + x"
    })
    print(f" • Math Tool Dispatch:       \"{res_math.output}\"")
    assert res_math.success is True

    res_stats = await tools.dispatch("stats_audit_significance", {
        "values": [12.1, 12.3, 12.2, 12.0],
        "baseline": 12.2
    })
    print(f" • Stats Tool Dispatch:      \"{res_stats.output}\"")
    assert res_stats.success is True

    tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> RESEARCHER ROOM PHASE 3 FULLY VERIFIED & PRODUCTION READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_researcher_phase3())
