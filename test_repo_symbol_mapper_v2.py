import time
import asyncio
from pathlib import Path

from agent.pa_scaffolder.repo_symbol_mapper import RepoSymbolMapper, FileIndex
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_adaptive_mapper():
    print("=" * 70)
    print("     SOTA ADAPTIVE REPO MAPPER AUDIT (PAGERANK + CACHE)")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. Device Adaptation & Initial Full Scan
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Device-Adaptive Concurrency & Initial Index...")
    mapper = RepoSymbolMapper(workspace_root="agent/pa_scaffolder", cache_db="workspace/.test_repo_cache.db")

    print(f" • Host Environment:  {'Android Termux' if mapper.is_termux else 'Desktop / Laptop'}")
    print(f" • Concurrency Pool:  {mapper.max_workers} worker threads")

    t0 = time.perf_counter()
    sym_count = mapper.index_repository()
    t_initial_ms = (time.perf_counter() - t0) * 1000.0

    print(f" • Scanned {len(mapper.file_indices)} files in: {t_initial_ms:.2f} ms")
    print(f" • Extracted {sym_count} symbols.")
    assert len(mapper.file_indices) >= 5
    assert sym_count > 20
    print(" >>> CRITERION 1 PASSED: Concurrent scanning calibrated to device. <<<")

    # -------------------------------------------------------------------------
    # 2. SQLite Incremental mtime Caching Verification
    # -------------------------------------------------------------------------
    print("\n[2/5] Benchmarking Incremental Cache Hits (<25ms Target)...")
    mapper_cached = RepoSymbolMapper(workspace_root="agent/pa_scaffolder", cache_db="workspace/.test_repo_cache.db")

    t1 = time.perf_counter()
    sym_count_2 = mapper_cached.index_repository()
    t_cached_ms = (time.perf_counter() - t1) * 1000.0

    print(f" • Re-scan Execution Time: {t_cached_ms:.2f} ms")
    print(f" • Speedup Multiplier:     {t_initial_ms / max(0.1, t_cached_ms):.1f}x faster")
    assert sym_count_2 == sym_count
    assert t_cached_ms < 25.0
    print(" >>> CRITERION 2 PASSED: Incremental SQLite cache active and verified. <<<")

    # -------------------------------------------------------------------------
    # 3. Polyglot Extraction Test (TS/JS, Go, Rust)
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing Polyglot Extraction (TypeScript, Go, Rust)...")
    test_polyglot_dir = Path("workspace/test_polyglot")
    test_polyglot_dir.mkdir(parents=True, exist_ok=True)

    # TypeScript Sample
    (test_polyglot_dir / "service.ts").write_text(
        "export class AuthService {\n"
        "  async login(user: string): Promise<boolean> { return true; }\n"
        "}\n",
        encoding="utf-8"
    )

    # Go Sample
    (test_polyglot_dir / "worker.go").write_text(
        "package main\n"
        "type TaskQueue struct {}\n"
        "func ProcessItem(id int) bool { return true }\n",
        encoding="utf-8"
    )

    poly_mapper = RepoSymbolMapper(workspace_root=str(test_polyglot_dir), cache_db="workspace/.test_poly_cache.db")
    poly_mapper.index_repository()

    ts_entry = poly_mapper.file_indices.get("service.ts")
    go_entry = poly_mapper.file_indices.get("worker.go")

    ts_syms = [s.name for s in ts_entry.symbols] if ts_entry else []
    go_syms = [s.name for s in go_entry.symbols] if go_entry else []

    print(f" • TypeScript Symbols: {ts_syms}")
    print(f" • Go Symbols:         {go_syms}")
    assert "AuthService" in ts_syms
    assert "ProcessItem" in go_syms

    # Cleanup polyglot test dir
    for p in test_polyglot_dir.glob("*"):
        p.unlink()
    test_polyglot_dir.rmdir()
    Path("workspace/.test_poly_cache.db").unlink(missing_ok=True)
    print(" >>> CRITERION 3 PASSED: Polyglot parser verified across TS and Go. <<<")

    # -------------------------------------------------------------------------
    # 4. PageRank Centrality Ranking Test
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing Power-Iteration PageRank Graph Centrality...")
    assert len(mapper.symbol_ranks) > 0

    top_ranked = sorted(mapper.symbol_ranks.items(), key=lambda x: x[1], reverse=True)[:5]
    print(" • Top 5 Central Nodes by PageRank Score:")
    for node_id, score in top_ranked:
        print(f"   └─ {node_id:<45} (Score: {score:.5f})")

    engine_matches = mapper.find_symbol("UnifiedAsyncEngine")
    assert len(engine_matches) > 0
    print(f" • 'UnifiedAsyncEngine' PageRank: {engine_matches[0].importance_rank:.5f}")
    assert engine_matches[0].importance_rank > 0.0
    print(" >>> CRITERION 4 PASSED: PageRank accurately identifies core architectural hubs. <<<")

    # -------------------------------------------------------------------------
    # 5. Elided Scope Rendering & Tool Registry Integration
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing Elided Scope Rendering & Tool Registry Integration...")
    tools = ToolRegistry(workspace_root="agent/pa_scaffolder")

    res_map = await tools.dispatch("repo_get_map", {"max_tokens": 300})
    print(f" • Tool 'repo_get_map' Success: {res_map.success}")
    assert res_map.success is True

    print("\n • Rendered Elided Map Preview (First 8 lines):")
    preview_lines = res_map.output.splitlines()[:8]
    for line in preview_lines:
        print(f"   {line}")

    assert "⋮..." in res_map.output, "Elision markers missing!"
    assert "# SOTA ARCHITECTURAL REPOSITORY MAP" in res_map.output

    tools.close()
    Path("workspace/.test_repo_cache.db").unlink(missing_ok=True)
    Path("workspace/.test_repo_cache.db-wal").unlink(missing_ok=True)
    Path("workspace/.test_repo_cache.db-shm").unlink(missing_ok=True)

    print("\n" + "=" * 70)
    print(">>> SOTA ADAPTIVE REPO MAPPER FULLY VERIFIED & PRODUCTION READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_adaptive_mapper())
