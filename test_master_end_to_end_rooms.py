import os
import sys
import json
import time
import shutil
import asyncio
import subprocess
from pathlib import Path

from agent.pa_scaffolder.rooms_engine import (
    RoomsEngine, AgentMode, SystemTelemetryCache,
    PaperRecord, ClaimRecord, DeadEndRecord
)
from agent.pa_scaffolder.pty_sandbox import InteractiveSandboxSession
from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher
from agent.pa_scaffolder.model_router import ModelAgnosticRouter, TaskProfile
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def run_master_integration_benchmark():
    print("=" * 76)
    print("     MASTER AUTONOMOUS AGENT WORKSTATION: END-TO-END INTEGRATION")
    print("=" * 76)

    master_ws = Path("workspace/master_sandbox").resolve()
    shutil.rmtree(master_ws, ignore_errors=True)
    master_ws.mkdir(parents=True, exist_ok=True)

    t_suite_start = time.perf_counter()

    # =========================================================================
    # PHASE 1: UNIVERSAL MODEL SWITCHER & RECENT FRONTIER MODEL REGISTRATION
    # =========================================================================
    print("\n[PHASE 1/5] Testing Universal Model Switcher & Dynamic Registration...")
    reg_file = master_ws / "model_registry.json"
    shutil.copy("agent/pa_scaffolder/model_registry.json", reg_file)

    switcher = UniversalModelSwitcher(registry_path=reg_file)

    # 1. Register a new frontier model dynamically
    frontier_id = "frontier_next_2026"
    ok_reg, reg_msg = switcher.register_new_model(
        backend_id=frontier_id,
        provider="anthropic",
        model_name="claude-3-8-opus-2026",
        context_window=1000000,
        cost_per_m_in=5.0,
        cost_per_m_out=25.0
    )
    print(f" • Dynamic Registration:       {reg_msg}")
    assert ok_reg is True

    # 2. Hot-swap Builder Room to the new model
    engine = RoomsEngine(workspace_root=str(master_ws))
    engine.model_switcher = switcher
    ok_sw, sw_msg = engine.switch_model_backend("builder", frontier_id)
    print(f" • Room Hot-Swap:             {sw_msg}")
    assert ok_sw is True
    assert engine.REGISTRY[AgentMode.BUILDER].preferred_backend == frontier_id

    # 3. Hot-swap Task Profile & Verify Router Synchronization
    ok_task, _ = switcher.switch_task_model(TaskProfile.DEEP_REASONING, "deepseek_r1")
    router_ep = engine.model_router.resolve_optimal_endpoint(TaskProfile.DEEP_REASONING)[0]
    print(f" • Router Task Sync:          DEEP_REASONING -> {router_ep.backend_id} ({router_ep.model_name})")
    assert router_ep.backend_id == "deepseek_r1"
    print(" >>> PHASE 1 PASSED: Universal Model Switcher fully dynamic & in-sync. <<<")

    # =========================================================================
    # PHASE 2: BUILDER ROOM (SWE-BENCH AUTONOMOUS MULTI-FILE FIX & GIT STASH)
    # =========================================================================
    print("\n[PHASE 2/5] Testing Builder Room Multi-File Red-to-Green Loop & Stash...")
    git_repo = master_ws / "repo"
    git_repo.mkdir(parents=True, exist_ok=True)

    # Initialize Git repository
    subprocess.run(["git", "init"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "MasterAgent"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@master.local"], cwd=str(git_repo), capture_output=True)

    # Base code setup
    (git_repo / "compute.py").write_text("def scale_tensor(x, factor):\n    return x * factor\n", encoding="utf-8")
    (git_repo / "service.py").write_text("from compute import scale_tensor\ndef run(val):\n    return scale_tensor(val) # TypeError: missing factor\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial baseline"], cwd=str(git_repo), capture_output=True)

    # Simulate in-progress user work that MUST NOT be destroyed
    dirty_file = git_repo / "uncommitted_notes.txt"
    dirty_file.write_text("CRITICAL ACTIVE USER SCRATCHPAD\n", encoding="utf-8")

    # Define Red reproduction test
    reproduce_code = (
        "import sys\n"
        "from service import run\n"
        "try:\n"
        "    res = run(10)\n"
        "    assert res == 50\n"
        "    sys.exit(0)\n"
        "except Exception as e:\n"
        "    print(f'CRASH: {e}')\n"
        "    sys.exit(1)\n"
    )

    # Solver providing multi-file atomic patch
    def multi_file_solver(task_desc, err_log):
        return {
            "compute.py": "def scale_tensor(x, factor=5):\n    return x * factor\n",
            "service.py": "from compute import scale_tensor\ndef run(val):\n    return scale_tensor(val, 5)\n"
        }

    builder_pty = InteractiveSandboxSession(workspace_root=str(git_repo))
    builder_engine = RoomsEngine(workspace_root=str(git_repo))

    t_build_start = time.perf_counter()
    build_result = await builder_engine.execute_builder_task(
        task_description="Fix TypeError in service.py calling compute.py",
        reproduce_code=reproduce_code,
        patch_solver_fn=multi_file_solver,
        pty_session=builder_pty,
        user_persona="engineer"
    )
    t_build_elapsed = time.perf_counter() - t_build_start

    print(f" • Builder Status:            {build_result.status} (in {build_result.attempts_taken} attempt)")
    print(f" • Shadow Branch:             {build_result.shadow_branch}")
    print(f" • Build Latency:             {t_build_elapsed:.2f}s")
    assert build_result.success is True
    assert build_result.status == "GREEN_VERIFIED"

    # Verify uncommitted user work was stashed and restored intact
    assert dirty_file.exists(), "CRITICAL: Dirty user worktree was lost!"
    print(f" • Stash Guard Verification:  \"{dirty_file.read_text().strip()}\" restored intact.")
    builder_pty.close()
    print(" >>> PHASE 2 PASSED: Multi-file Red-to-Green task resolved & committed. <<<")

    # =========================================================================
    # PHASE 3: TESTER ROOM (SELF-HEALING META-AGENT PIPELINE)
    # =========================================================================
    print("\n[PHASE 3/5] Testing Tester Room Self-Healing Meta-Agent...")
    harness = UnifiedAsyncEngine()
    harness.tools.workspace_root = master_ws

    # Create dummy 50-line source file for the task
    (master_ws / "large_source.py").write_text("".join(f"# Line {i}\n" for i in range(1, 55)), encoding="utf-8")

    tool_file = Path("agent/pa_scaffolder/tool_registry.py")
    orig_tool_code = tool_file.read_text(encoding="utf-8")

    try:
        # Inject an intentional crash into the internal PA tool
        bug_anchor = "lines = fpath.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines(keepends=True)"
        bug_injection = (
            "lines = fpath.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines(keepends=True)\n"
            "                if int(args.get('line_count', 0)) > 25:\n"
            "                    raise IndexError('Simulated PA Buffer Overflow')\n"
        )
        assert bug_anchor in orig_tool_code
        tool_file.write_text(orig_tool_code.replace(bug_anchor, bug_injection, 1), encoding="utf-8")

        # Hot-reload buggy class
        harness.self_healer.hot_reload_module("agent/pa_scaffolder/tool_registry.py")
        mod = sys.modules["agent.pa_scaffolder.tool_registry"]
        harness.tools = mod.ToolRegistry(workspace_root=master_ws)

        # Synthesizer to fix the internal bug
        def self_repair_synthesizer(rel_path: str, faulty_code: str, err_trace: str) -> str:
            return faulty_code.replace("if int(args.get('line_count', 0)) > 25:\n                    raise IndexError('Simulated PA Buffer Overflow')\n", "")

        user_query_args = {"file_path": "large_source.py", "start_line": 5, "line_count": 35}

        t_heal_start = time.perf_counter()
        heal_res = await harness.dispatch_tool_with_self_healing(
            tool_name="file_read",
            tool_args=user_query_args,
            patch_synthesizer=self_repair_synthesizer
        )
        t_heal_elapsed = time.perf_counter() - t_heal_start

        print(f" • Self-Healed Status:        {heal_res.get('repaired')}")
        print(f" • Task Resumed Success:      {heal_res.get('success')}")
        print(f" • Repair Latency:            {t_heal_elapsed:.3f}s")
        print(f" • Diagnostic Log:            \"{heal_res.get('explanation')}\"")

        assert heal_res.get("success") is True
        assert heal_res.get("repaired") is True
        assert "Line 5" in heal_res.get("output")
        assert "Line 38" in heal_res.get("output")

    finally:
        # Restore clean tool_registry
        tool_file.write_text(orig_tool_code, encoding="utf-8")
        harness.self_healer.hot_reload_module("agent/pa_scaffolder/tool_registry.py")
        harness.tools = sys.modules["agent.pa_scaffolder.tool_registry"].ToolRegistry(workspace_root=master_ws)

    print(" >>> PHASE 3 PASSED: Tester intercepted crash, self-patched, and resumed task. <<<")

    # =========================================================================
    # PHASE 4: RESEARCHER ROOM (FULL SCIENTIFIC RESEARCH & MATH PIPELINE)
    # =========================================================================
    print("\n[PHASE 4/5] Testing Researcher Room Full Pipeline...")
    res_engine = RoomsEngine(workspace_root=str(master_ws))

    # 1. SQLite WAL & FTS5 Indexing
    res_engine.research_memory.store_paper(PaperRecord(
        paper_id="doi:10.1145/kv_quant_2026",
        title="Dynamic Sub-Quadratic Quantization for Billion-Token Contexts",
        authors=["Alice Dev", "Bob Researcher"],
        year=2026,
        venue="ICML",
        abstract="FP8 non-uniform quantization compresses KV-cache by 44% with zero loss.",
        bibtex="@article{dev2026dynamic,\n  title={Dynamic Sub-Quadratic Quantization},\n  author={Alice Dev and Bob Researcher},\n  year={2026}\n}",
        citation_count=85
    ))
    res_engine.research_memory.store_claim(ClaimRecord(
        claim_id="cl_99",
        paper_id="doi:10.1145/kv_quant_2026",
        claim_text="FP8 quantization achieves 44% bandwidth reduction with perplexity < 6.4",
        section="Results",
        quote_span="44% bandwidth reduction across benchmarks",
        verification_status="verified",
        confidence=0.99
    ))
    res_engine.research_memory.record_dead_end(DeadEndRecord(
        dead_end_id="de_99",
        hypothesis="Uniform 2-bit scalar quantization",
        failed_mechanism="Outlier scale divergence across intermediate layers",
        compute_expended_hrs=24.0,
        root_cause="Outliers in layer 20 exceed 2-bit dynamic range"
    ))

    # FTS5 Search benchmark
    t_search_0 = time.perf_counter()
    search_hits = res_engine.research_memory.search_papers("Quantization", limit=3)
    t_search_ms = (time.perf_counter() - t_search_0) * 1000.0
    print(f" • SQLite WAL FTS5 Latency:   {t_search_ms:.2f} ms (Found: {len(search_hits)})")
    assert len(search_hits) >= 1

    # 2. Time-Decayed PageRank Ranking
    ranked_papers = res_engine.rank_influential_papers("Quantization")
    print(f" • Time-Decayed PageRank:     #1: \"{ranked_papers[0]['title']}\" (Score: {ranked_papers[0]['composite_impact_score']})")
    assert len(ranked_papers) >= 1

    # 3. Math & Symbolic Verification
    ok_sym, sym_msg = res_engine.verify_mathematical_derivation("x * (a + b)", "x * a + x * b", ["x", "a", "b"])
    print(f" • Symbolic Math Proof:       {sym_msg}")
    assert ok_sym is True

    # 4. Sandboxed Multi-Seed Experiment Sweep & Welch t-test
    sweep_script = (
        "import argparse, random, json\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--seed', type=int, default=42)\n"
        "args = parser.parse_args()\n"
        "random.seed(args.seed)\n"
        "perplexity = round(6.36 + random.uniform(0.01, 0.04), 3)\n"
        "print(json.dumps({'perplexity': perplexity}))\n"
    )
    (master_ws / "eval_perplexity.py").write_text(sweep_script, encoding="utf-8")

    sweep_res = await res_engine.run_experiment_sweep(
        script_rel_path="eval_perplexity.py",
        metric_key="perplexity",
        seeds=[42, 1337, 2026],
        baseline_target=6.38,
        paper_id="doi:10.1145/kv_quant_2026",
        name="KV Quant Perplexity Audit"
    )
    print(f" • Multi-Seed Sweep (N=3):    Mean = {sweep_res['stats_audit']['mean']} (Gap: {sweep_res['stats_audit']['reproduction_gap']:.2%})")
    print(f" • Statistical Sanity:        {sweep_res['stats_audit']['verdict']}")
    assert sweep_res["stats_audit"]["reproduction_gap"] < 0.05

    # 5. Publication LaTeX Drafting with BibTeX Reconciliation
    manuscript = res_engine.draft_research_manuscript(
        title="Sub-Quadratic Quantization Scaling",
        authors=["Alice Dev", "Bob Researcher"],
        sections={
            "Abstract": "We analyze low-rank dynamic quantization.",
            "Methodology": "Attention projections are quantized:\n$$A = \\text{softmax}(Q K^T / \\sqrt{d})$$\nAs shown in \\cite{dev2026dynamic}.",
            "Results": "| Precision | Perplexity |\n|---|---|\n| FP16 | 6.35 |\n| FP8 | 6.38 |\n"
        },
        output_rel_dir="docs/master_paper"
    )
    print(f" • Manuscript Generated:      {manuscript['tables_count']} table(s), {manuscript['equations_count']} equation(s)")
    assert (master_ws / "docs/master_paper/main.tex").exists()
    assert (master_ws / "docs/master_paper/references.bib").exists()

    # 6. Daily 5-Line Research Digest
    digest = res_engine.generate_daily_research_digest("Quantization")
    print(f" • 5-Line Daily Digest:       {len(digest['digest_5_lines'])} lines generated.")
    assert len(digest["digest_5_lines"]) == 5
    print(" >>> PHASE 4 PASSED: Researcher scientific pipeline fully operational. <<<")

    # =========================================================================
    # PHASE 5: CONVERSATIONAL VOICE & CHAT INTERCEPTOR
    # =========================================================================
    print("\n[PHASE 5/5] Testing Conversational Voice/Chat Multi-Room Dispatch...")
    conv_engine = UnifiedAsyncEngine()
    conv_engine.rooms.workspace = master_ws
    conv_engine.rooms.model_switcher = switcher

    # Voice command: switch to tester mode
    res_v1 = await conv_engine.process_voice_turn("enter tester mode")
    print(f" • Utterance 1: \"enter tester mode\" -> Spoken: \"{res_v1.get('spoken_response')}\"")
    assert conv_engine.rooms.current_mode == AgentMode.TESTER

    # Voice command: switch mode model
    res_v2 = await conv_engine.process_voice_turn("switch tester to deepseek_r1")
    print(f" • Utterance 2: \"switch tester to deepseek_r1\" -> Spoken: \"{res_v2.get('spoken_response')}\"")
    assert res_v2.get("type") == "MODEL_SWITCH_SUCCESS"

    # Voice command: list models overview
    res_v3 = await conv_engine.process_voice_turn("show active models")
    print(f" • Utterance 3: \"show active models\" -> Spoken: \"{res_v3.get('spoken_response')}\"")
    assert res_v3.get("type") == "MODEL_LIST_OVERVIEW"

    t_suite_total = time.perf_counter() - t_suite_start
    print(" >>> PHASE 5 PASSED: Conversational turns orchestrate rooms & models seamlessly. <<<")

    # Teardown
    harness.tools.close()
    conv_engine.tools.close()
    shutil.rmtree(master_ws, ignore_errors=True)

    print("\n" + "=" * 76)
    print(f">>> ALL 5 PHASES VERIFIED: SYSTEM 100% OPERATIONAL IN {t_suite_total:.2f}s <<<")
    print("=" * 76)


if __name__ == "__main__":
    asyncio.run(run_master_integration_benchmark())
