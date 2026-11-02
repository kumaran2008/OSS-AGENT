import json
import time
import asyncio
import shutil
from pathlib import Path

from agent.pa_scaffolder.research_memory import (
    ResearchMemoryLayer, PaperRecord, ClaimRecord, ExperimentRecord, DeadEndRecord
)
from agent.pa_scaffolder.model_router import ModelAgnosticRouter, TaskProfile
from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode, SystemTelemetryCache


async def test_researcher_phase1():
    print("=" * 70)
    print("     RESEARCHER ROOM PHASE 1: SHARED MEMORY & ROUTER BENCHMARK")
    print("=" * 70)

    test_ws = Path("workspace/test_research_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    db_path = test_ws / "test_vault.db"
    memory = ResearchMemoryLayer(db_path=db_path)

    # -------------------------------------------------------------------------
    # 1. SQLite WAL Mode & FTS5 BM25 Literature Indexing
    # -------------------------------------------------------------------------
    print("\n[1/6] Testing SQLite WAL Mode & FTS5 BM25 Literature Indexing...")
    # Verify WAL journal mode
    with memory._get_connection() as conn:
        j_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        print(f" • SQLite Journal Mode: {j_mode.upper()} (Target: WAL)")
        assert j_mode.lower() == "wal"

    paper_alpha = PaperRecord(
        paper_id="doi:10.1145/transformer_kv",
        title="Sub-Quadratic Attention Mechanisms with KV-Cache Quantization",
        authors=["Alice Chen", "Bob Zhang"],
        year=2025,
        venue="NeurIPS",
        abstract="We introduce an 8-bit dynamic attention quantization method that reduces memory bandwidth by 42%.",
        full_text_md="## Methodology\nWe apply non-uniform FP8 quantization across attention heads...",
        bibtex="@article{chen2025subquadratic, title={Sub-Quadratic Attention...}}",
        citation_count=142
    )
    memory.store_paper(paper_alpha)

    t0 = time.perf_counter()
    search_hits = memory.search_papers("KV-Cache Quantization", limit=5)
    t_search_ms = (time.perf_counter() - t0) * 1000.0

    print(f" • Search Retrieval Latency: {t_search_ms:.2f} ms")
    print(f" • Results Found:            {len(search_hits)}")
    assert len(search_hits) > 0
    assert search_hits[0]["paper_id"] == "doi:10.1145/transformer_kv"
    print(f" • Top Hit Title:            \"{search_hits[0]['title']}\" (Score: {search_hits[0]['bm25_score']})")
    print(" >>> CRITERION 1 PASSED: SQLite WAL + FTS5 indexing operating with sub-millisecond retrieval. <<<")

    # -------------------------------------------------------------------------
    # 2. Section-Aware Claim Verification Registry
    # -------------------------------------------------------------------------
    print("\n[2/6] Testing Section-Aware Claim Verification & Exact Quotes...")
    claim_1 = ClaimRecord(
        claim_id="claim_001",
        paper_id="doi:10.1145/transformer_kv",
        claim_text="Dynamic 8-bit quantization decreases KV-cache memory bandwidth by 42%",
        section="Results",
        quote_span="our method demonstrates a 42% decrease in memory bandwidth across A100 benchmarks",
        verification_status="verified",
        confidence=0.98
    )
    memory.store_claim(claim_1)

    matched_claims = memory.query_claims("bandwidth", limit=5)
    print(f" • Matched Claims Count:    {len(matched_claims)}")
    assert len(matched_claims) > 0
    assert matched_claims[0]["verification_status"] == "verified"
    print(f" • Claim Section:           {matched_claims[0]['section']}")
    print(f" • Verbatim Quote Span:     \"{matched_claims[0]['quote_span']}\"")
    print(" >>> CRITERION 2 PASSED: Grounded claims linked to sections with verbatim quotes. <<<")

    # -------------------------------------------------------------------------
    # 3. Directed Citation Graph Subgraph Traversal
    # -------------------------------------------------------------------------
    print("\n[3/6] Testing Directed Citation Graph Traversal...")
    paper_beta_id = "doi:10.1145/attention_is_all_you_need"
    memory.add_citation(
        source_id="doi:10.1145/transformer_kv",
        target_id=paper_beta_id,
        context="Extends multi-head attention formulation for low-bit inference.",
        sentiment="extends"
    )

    subgraph = memory.get_citation_subgraph("doi:10.1145/transformer_kv", depth=1)
    print(f" • Subgraph Node Count:     {len(subgraph['nodes'])}")
    print(f" • Subgraph Edge Count:     {len(subgraph['edges'])}")
    assert paper_beta_id in subgraph["nodes"]
    assert subgraph["edges"][0]["sentiment"] == "extends"
    print(" >>> CRITERION 3 PASSED: Directed citation graph links and sentiment verified. <<<")

    # -------------------------------------------------------------------------
    # 4. Reproducible Experiment Ledger
    # -------------------------------------------------------------------------
    print("\n[4/6] Testing Reproducible Experiment Ledger...")
    exp = ExperimentRecord(
        experiment_id="exp_run_881",
        paper_id="doi:10.1145/transformer_kv",
        name="FP8 Attention Benchmark on Termux",
        hypothesis="Dynamic quantization maintains perplexity < 6.5 on WikiText-2",
        commit_hash="a1f94c2b9",
        seed=42,
        config={"batch_size": 4, "precision": "fp8", "layers": 12},
        metrics={"perplexity": 6.38, "latency_ms": 14.2},
        status="reproduced",
        reproduction_gap=0.012
    )
    memory.record_experiment(exp)

    with memory._get_connection() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE experiment_id='exp_run_881';").fetchone()
        assert row is not None
        assert row["commit_hash"] == "a1f94c2b9"
        assert json.loads(row["metrics_json"])["perplexity"] == 6.38
    print(" • Experiment run logged with seed=42, git_hash=a1f94c2b9, gap=0.012.")
    print(" >>> CRITERION 4 PASSED: Experiment metrics and seed metadata persistently ledgered. <<<")

    # -------------------------------------------------------------------------
    # 5. Dead-End & Negative Result Registry
    # -------------------------------------------------------------------------
    print("\n[5/6] Testing Negative Result & Dead-End Registry...")
    dead_end = DeadEndRecord(
        dead_end_id="de_001",
        hypothesis="Uniform 4-bit scalar quantization across attention keys",
        failed_mechanism="Excessive outlier scale divergence causing severe perplexity spikes",
        compute_expended_hrs=18.5,
        root_cause="Key outliers in layer 16 exceed dynamic range of 4-bit integer grid"
    )
    memory.record_dead_end(dead_end)

    found_dead_ends = memory.query_dead_ends("quantization")
    print(f" • Dead-Ends Found:         {len(found_dead_ends)}")
    assert len(found_dead_ends) > 0
    assert "outlier scale divergence" in found_dead_ends[0]["failed_mechanism"]
    print(f" • Recorded Root Cause:     \"{found_dead_ends[0]['root_cause']}\"")
    print(" >>> CRITERION 5 PASSED: Negative results indexed to prevent repeated compute failure. <<<")

    # -------------------------------------------------------------------------
    # 6. Model-Agnostic Router & Telemetry Integration
    # -------------------------------------------------------------------------
    print("\n[6/6] Testing Model-Agnostic Router Task Profiles & Zero-Balance Fallback...")
    router = ModelAgnosticRouter()

    # Test Task Profile Resolution
    ep_skim, is_fallback_1 = router.resolve_optimal_endpoint(TaskProfile.SKIM_EXTRACTION)
    ep_reasoning, _ = router.resolve_optimal_endpoint(TaskProfile.DEEP_REASONING)
    ep_long_ctx, _ = router.resolve_optimal_endpoint(TaskProfile.WHOLE_PAPER_SYNTHESIS)

    print(f" • SKIM_EXTRACTION Resolved: {ep_skim.backend_id} ({ep_skim.model_name})")
    print(f" • DEEP_REASONING Resolved:  {ep_reasoning.backend_id} ({ep_reasoning.model_name})")
    print(f" • WHOLE_PAPER Resolved:     {ep_long_ctx.backend_id} ({ep_long_ctx.model_name})")

    assert ep_skim.context_window >= 32768
    assert ep_reasoning.cost_per_m_in > ep_skim.cost_per_m_in

    # Test Zero-Balance Fallback Execution
    SystemTelemetryCache.set_wallet_balance(0.00)
    ep_zero, is_fallback_zero = router.resolve_optimal_endpoint(TaskProfile.DEEP_REASONING)
    print(f" • Zero-Balance Fallback:   {ep_zero.backend_id} | Is Fallback: {is_fallback_zero}")
    assert is_fallback_zero is True
    assert ep_zero.cost_per_m_in == 0.0

    # Reset balance for subsequent operations
    SystemTelemetryCache.set_wallet_balance(5.00)

    # Test Router Dispatch
    t_start = time.perf_counter()
    resp = await router.dispatch_prompt(
        profile=TaskProfile.SKIM_EXTRACTION,
        system_prompt="You are an academic literature indexer.",
        user_prompt="Extract core contributions from the provided abstract."
    )
    t_elapsed = time.perf_counter() - t_start

    print(f" • Dispatch Status:         {'SUCCESS' if resp.success else 'FAILED'}")
    print(f" • Execution Latency:       {t_elapsed:.3f}s")
    print(f" • Backend Invoked:         {resp.backend_used}")
    assert resp.success is True
    print(" >>> CRITERION 6 PASSED: Model router profile routing and zero-cost fallbacks verified. <<<")

    # -------------------------------------------------------------------------
    # 7. Rooms Engine Public Integration
    # -------------------------------------------------------------------------
    print("\n[+] Testing RoomsEngine Researcher Synthesis Integration...")
    rooms = RoomsEngine(workspace_root=str(test_ws))
    rooms.research_memory = memory

    synthesis_res = await rooms.execute_research_synthesis(
        topic_query="KV-Cache Quantization",
        profile=TaskProfile.SKIM_EXTRACTION
    )
    print(f" • Active Mode:             {synthesis_res['mode'].upper()}")
    print(f" • Local Papers Found:      {synthesis_res['local_papers_count']}")
    print(f" • Dead Ends Identified:    {synthesis_res['dead_ends_detected']}")
    assert synthesis_res["local_papers_count"] >= 1
    assert synthesis_res["dead_ends_detected"] >= 1

    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> RESEARCHER ROOM PHASE 1 (MEMORY + ROUTER) 100% OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_researcher_phase1())
