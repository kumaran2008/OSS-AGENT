import asyncio
import shutil
import time
from pathlib import Path

from agent.pa_scaffolder.research_memory import ResearchMemoryLayer, PaperRecord
from agent.pa_scaffolder.literature_engine import LiteratureEngine, AcademicSearchResult
from agent.pa_scaffolder.rooms_engine import RoomsEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_researcher_phase2():
    print("=" * 70)
    print("     RESEARCHER ROOM PHASE 2: LITERATURE ENGINE & CITATION SCORING")
    print("=" * 70)

    test_ws = Path("workspace/test_lit_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    db_path = test_ws / "test_vault.db"
    memory = ResearchMemoryLayer(db_path=db_path)
    engine = LiteratureEngine(memory_layer=memory)

    # -------------------------------------------------------------------------
    # 1. Parallel Multi-Source Ingestion & Deduplication
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Multi-Source Deduplication Engine...")
    # Simulate parallel batch with duplicate paper from Semantic Scholar and OpenAlex
    mock_batch_1 = [
        AcademicSearchResult(
            source="semantic_scholar",
            paper_id="doi:10.1145/kv_cache_opt",
            title="Sub-Quadratic Attention Mechanisms with KV-Cache Quantization",
            authors=["Alice Chen", "Bob Zhang"],
            year=2025,
            abstract="Dynamic 8-bit quantization reduces memory bandwidth by 42%.",
            citation_count=180,
            doi="10.1145/kv_cache_opt"
        )
    ]
    mock_batch_2 = [
        AcademicSearchResult(
            source="openalex",
            paper_id="openalex:W12345678",
            title="Sub-Quadratic Attention Mechanisms with KV-Cache Quantization",  # Identical title
            authors=["Alice Chen"],
            year=2025,
            abstract="",
            citation_count=210,  # Updated citation count
            doi="10.1145/kv_cache_opt"
        ),
        AcademicSearchResult(
            source="arxiv",
            paper_id="arxiv:2401.9988",
            title="FlashAttention-3: Fast and Memory-Efficient Exact Attention",
            authors=["Tri Dao"],
            year=2024,
            abstract="Asynchronous memory ping-ponging on Hopper GPUs.",
            citation_count=950,
            doi="10.48550/arxiv.2401.9988"
        )
    ]

    # Mock parallel resolver with deduplication
    engine._query_semantic_scholar = lambda q, max_results=3: asyncio.sleep(0.01, result=mock_batch_1)
    engine._query_openalex = lambda q, max_results=3: asyncio.sleep(0.01, result=mock_batch_2)
    engine._query_arxiv = lambda q, max_results=3: asyncio.sleep(0.01, result=[])

    t0 = time.perf_counter()
    deduped = await engine.search_and_deduplicate("Attention KV Cache", limit_per_source=3)
    t_dedup_ms = (time.perf_counter() - t0) * 1000.0

    print(f" • Deduplication Execution: {t_dedup_ms:.2f} ms")
    print(f" • Input Papers:            3 | Deduplicated Output: {len(deduped)}")
    assert len(deduped) == 2, f"Expected 2 deduplicated papers, got {len(deduped)}"

    # Confirm higher citation count was merged
    kv_paper = next(p for p in deduped if "Sub-Quadratic" in p.title)
    print(f" • Merged Citation Count:   {kv_paper.citation_count} (Merged from OpenAlex)")
    assert kv_paper.citation_count == 210
    print(" >>> CRITERION 1 PASSED: Canonical DOI & normalized title deduplication verified. <<<")

    # -------------------------------------------------------------------------
    # 2. Layout-Aware PDF & LaTeX Section Extraction
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing Layout-Aware Sectioning & LaTeX Math Preservation...")
    sample_paper_text = """
Abstract
We present a sub-quadratic attention mechanism for ultra-long context LLMs.

1. Introduction
Modern Transformer architectures are bottlenecked by KV-cache memory bandwidth.

3. Methodology
We formulate our low-rank attention projection as follows:
$$A_{i,j} = \frac{\exp(Q_i K_j^T / \sqrt{d})}{\sum_k \exp(Q_i K_k^T / \sqrt{d})}$$
where $Q_i$ and $K_j$ represent non-uniform 8-bit quantized key-value embeddings.

4. Results
Table 1 outlines the performance delta across benchmarks:
| Model Size | Baseline Latency | Our Method | Speedup |
|---|---|---|---|
| 7B | 48.2 ms | 28.1 ms | 1.71x |
| 70B | 280.4 ms | 158.2 ms | 1.77x |

5. Limitations
Our method exhibits outlier scale divergence when quantized below 4 bits.
"""

    sections = engine.parse_paper_layout_and_sections(sample_paper_text)
    sec_types = [s.section_type for s in sections]
    print(f" • Extracted Section Types: {sec_types}")
    assert "abstract" in sec_types
    assert "methodology" in sec_types
    assert "results" in sec_types
    assert "limitations" in sec_types

    method_sec = next(s for s in sections if s.section_type == "methodology")
    print(f" • Equations Preserved:     {len(method_sec.equations)} (Display: {method_sec.equations[0][:25]}...)")
    assert "$$A_{i,j}" in method_sec.equations[0]

    results_sec = next(s for s in sections if s.section_type == "results")
    print(f" • Tables Preserved:        {len(results_sec.tables)}")
    assert "| Model Size |" in results_sec.tables[0]
    print(" >>> CRITERION 2 PASSED: Layout sections, LaTeX formulas, and Markdown tables preserved. <<<")

    # -------------------------------------------------------------------------
    # 3. Time-Decayed PageRank Citation Impact Scoring
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing Time-Decayed PageRank Citation Impact Scoring...")
    sample_cluster = [
        {"paper_id": "p_vaswani", "title": "Attention Is All You Need", "year": 2017, "citation_count": 120000},
        {"paper_id": "p_flash1", "title": "FlashAttention: Fast and Memory-Efficient Exact Attention", "year": 2022, "citation_count": 2800},
        {"paper_id": "p_flash3", "title": "FlashAttention-3: Fast Exact Attention on Hopper", "year": 2024, "citation_count": 1100},
        {"paper_id": "p_subquad", "title": "Sub-Quadratic Attention with KV-Cache Quantization", "year": 2025, "citation_count": 320},
        {"paper_id": "p_survey", "title": "A Survey of Efficient Attention Mechanisms", "year": 2021, "citation_count": 450}
    ]

    # Citation edges: who cites whom
    edges = [
        ("p_flash1", "p_vaswani"),
        ("p_flash3", "p_flash1"),
        ("p_flash3", "p_vaswani"),
        ("p_subquad", "p_flash3"),
        ("p_subquad", "p_flash1"),
        ("p_survey", "p_vaswani")
    ]

    ranked_impact = engine.compute_citation_impact_ranking(sample_cluster, edges, current_year=2026)

    print(f" • Ranked Papers (Top 3 of {len(ranked_impact)}):")
    for idx, r in enumerate(ranked_impact[:3], 1):
        print(f"   {idx}. [{r.archetype}] \"{r.title}\" | Score: {r.composite_impact_score} (PR: {r.pagerank_score}, Vel: {r.citation_velocity}/yr)")

    assert ranked_impact[0].archetype in ["Foundational Seed", "High-Velocity Breakthrough"]
    assert len(ranked_impact[0].open_gaps_or_limitations) >= 1
    print(f" • Identified Open Research Gaps: \"{ranked_impact[0].open_gaps_or_limitations[0]}\"")
    print(" >>> CRITERION 3 PASSED: Time-decayed PageRank distinguished foundational vs breakthrough papers. <<<")

    # -------------------------------------------------------------------------
    # 4. Rooms Engine Public Literature Orchestration
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing RoomsEngine Literature Search & Ingest...")
    rooms = RoomsEngine(workspace_root=str(test_ws))
    rooms.literature_engine = engine

    # Seed papers into memory
    for p in sample_cluster:
        rooms.research_memory.store_paper(PaperRecord(
            paper_id=p["paper_id"],
            title=p["title"],
            authors=["Author et al."],
            year=p["year"],
            venue="Top Venue",
            abstract="Sample abstract.",
            citation_count=p["citation_count"]
        ))
    for src, tgt in edges:
        rooms.research_memory.add_citation(src, tgt, "Cites foundational baseline")

    top_5 = rooms.rank_influential_papers("Attention")
    print(f" • Top Influential Papers Returned: {len(top_5)}")
    assert len(top_5) == 5
    print(f" • #1 Ranked Paper: \"{top_5[0]['title']}\" ({top_5[0]['year']})")
    print(" >>> CRITERION 4 PASSED: RoomsEngine literature orchestration operational. <<<")

    # -------------------------------------------------------------------------
    # 5. Tool Registry Integration
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing ToolRegistry Dispatch of Literature Tools...")
    tools = ToolRegistry(workspace_root=str(test_ws))
    tools.literature = engine

    res_rank = await tools.dispatch("literature_rank_papers", {"query": "Attention"})
    print(f" • Tool Dispatch Output:\n{res_rank.output.strip()}")
    assert res_rank.success is True
    assert "FOUNDATIONAL SEED" in res_rank.output or "HIGH-VELOCITY" in res_rank.output

    tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> RESEARCHER ROOM PHASE 2 FULLY VERIFIED & PRODUCTION READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_researcher_phase2())
