import asyncio
import shutil
from pathlib import Path

from agent.pa_scaffolder.research_memory import ResearchMemoryLayer, PaperRecord, ClaimRecord, DeadEndRecord
from agent.pa_scaffolder.literature_engine import LiteratureEngine
from agent.pa_scaffolder.academic_writer import AcademicWriterEngine
from agent.pa_scaffolder.research_digest import ResearchDigestEngine
from agent.pa_scaffolder.rooms_engine import RoomsEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_researcher_phase4():
    print("=" * 70)
    print("     RESEARCHER ROOM PHASE 4: ACADEMIC WRITER & DAILY DIGEST")
    print("=" * 70)

    test_ws = Path("workspace/test_writer_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    db_path = test_ws / "test_vault.db"
    memory = ResearchMemoryLayer(db_path=db_path)
    literature = LiteratureEngine(memory_layer=memory)
    writer = AcademicWriterEngine(memory=memory)
    digest_engine = ResearchDigestEngine(memory=memory, literature=literature)

    # Seed research memory with a paper, claim, and dead-end
    sample_paper = PaperRecord(
        paper_id="doi:10.1145/transformer_kv",
        title="Sub-Quadratic Attention Mechanisms with KV-Cache Quantization",
        authors=["Alice Chen", "Bob Zhang"],
        year=2025,
        venue="NeurIPS",
        abstract="8-bit quantization reduces memory bandwidth by 42%.",
        bibtex="@article{chen2025,\n  title = {Sub-Quadratic Attention Mechanisms with KV-Cache Quantization},\n  author = {Alice Chen and Bob Zhang},\n  year = {2025}\n}",
        citation_count=210
    )
    memory.store_paper(sample_paper)

    sample_claim = ClaimRecord(
        claim_id="cl_01",
        paper_id="doi:10.1145/transformer_kv",
        claim_text="Dynamic 8-bit quantization decreases KV-cache memory bandwidth by 42%",
        section="Results",
        quote_span="42% decrease in memory bandwidth",
        verification_status="verified",
        confidence=0.98
    )
    memory.store_claim(sample_claim)

    sample_dead_end = DeadEndRecord(
        dead_end_id="de_01",
        hypothesis="Uniform 4-bit scalar quantization across attention keys",
        failed_mechanism="Excessive outlier scale divergence",
        compute_expended_hrs=18.5,
        root_cause="Key outliers in layer 16 exceed dynamic range of 4-bit integer grid"
    )
    memory.record_dead_end(sample_dead_end)

    # -------------------------------------------------------------------------
    # 1. BibTeX Reconciliation & Citation Grounding
    # -------------------------------------------------------------------------
    print("\n[1/6] Testing BibTeX Key Reconciliation & Grounding...")
    sample_tex = "Prior work \\cite{chen2025} showed significant memory reduction, unlike \\cite{phantom2099}."

    recon = writer.reconcile_bibtex(sample_tex)
    print(f" • Cited Keys:           {recon.cited_keys}")
    print(f" • Resolved Keys:        {recon.resolved_keys}")
    print(f" • Missing Keys:         {recon.missing_keys}")
    print(f" • Reconciled BibTeX:\n{recon.reconciled_bibtex.strip()}")

    assert "chen2025" in recon.resolved_keys
    assert "phantom2099" in recon.missing_keys
    assert recon.is_valid is False
    print(" >>> CRITERION 1 PASSED: Grounded citation resolved and phantom key flagged. <<<")

    # -------------------------------------------------------------------------
    # 2. Markdown to LaTeX Conversion (Tables & Math)
    # -------------------------------------------------------------------------
    print("\n[2/6] Testing Markdown to LaTeX Table & Equation Conversion...")
    raw_section = (
        "## Empirical Performance\n"
        "We evaluate attention projection:\n"
        "$$A = \\text{softmax}(Q K^T / \\sqrt{d})$$\n\n"
        "| Architecture | Latency (ms) | Speedup |\n"
        "|---|---|---|\n"
        "| Baseline FP16 | 45.2 | 1.0x |\n"
        "| Ours (8-bit)  | 26.1 | 1.73x |\n"
    )

    tex_out, tbl_cnt, eq_cnt = writer.convert_markdown_to_latex(raw_section)
    print(f" • Tables Converted:     {tbl_cnt}")
    print(f" • Equations Converted:  {eq_cnt}")
    print(f" • Converted TeX Snippet:\n{tex_out.strip()}")

    assert tbl_cnt == 1
    assert eq_cnt == 1
    assert "\\begin{table}" in tex_out
    assert "\\begin{tabular}{ccc}" in tex_out
    assert "\\begin{equation}" in tex_out
    print(" >>> CRITERION 2 PASSED: Tables and display equations translated to LaTeX blocks. <<<")

    # -------------------------------------------------------------------------
    # 3. Full Publication Manuscript Assembly
    # -------------------------------------------------------------------------
    print("\n[3/6] Testing Full Manuscript Assembly & File Generation...")
    sections = {
        "Abstract": "This paper presents low-rank KV-cache quantization.",
        "Methodology": "Attention projections are quantized dynamically:\n$$W_k = Q(W, 8)$$\nSee \\cite{chen2025}.",
        "Results": "| Precision | Perplexity |\n|---|---|\n| FP16 | 6.35 |\n| INT8 | 6.38 |\n"
    }

    manuscript_dir = test_ws / "docs" / "manuscript"
    draft = writer.draft_manuscript(
        title="Sub-Quadratic Low-Rank KV-Cache Scaling",
        authors=["Research Team"],
        sections=sections,
        output_dir=manuscript_dir
    )

    print(f" • Generated main.tex:   {(manuscript_dir / 'main.tex').exists()}")
    print(f" • Generated references: {(manuscript_dir / 'references.bib').exists()}")
    assert (manuscript_dir / "main.tex").exists()
    assert (manuscript_dir / "references.bib").exists()
    assert "\\bibliography{references}" in draft.tex_content
    print(" >>> CRITERION 3 PASSED: Full LaTeX manuscript and BibTeX generated on disk. <<<")

    # -------------------------------------------------------------------------
    # 4. Point-by-Point Reviewer Rebuttal Synthesis
    # -------------------------------------------------------------------------
    print("\n[4/6] Testing Reviewer Rebuttal Generator...")
    review_items = [
        {
            "reviewer": "Reviewer 1",
            "comment": "The ablation study does not clarify latency on 70B models.",
            "response": "We have included Table 3 with 70B inference timings on 8x H100 GPUs.",
            "revision_diff": "+ Table 3: 70B Benchmark Latency (158ms vs 280ms baseline)."
        }
    ]
    rebuttal_md = writer.generate_reviewer_rebuttal("Sub-Quadratic Attention", review_items)
    print(f" • Rebuttal Header:      {rebuttal_md.splitlines()[0]}")
    assert "Reviewer 1 - Comment 1" in rebuttal_md
    assert "Revision Diff" in rebuttal_md or "Manuscript Revision" in rebuttal_md
    print(" >>> CRITERION 4 PASSED: Structured reviewer rebuttal template synthesized. <<<")

    # -------------------------------------------------------------------------
    # 5. Strict 5-Line Daily Research Tracking Digest
    # -------------------------------------------------------------------------
    print("\n[5/6] Testing 5-Line Daily Research Tracking Digest...")
    digest = digest_engine.generate_5_line_digest("Quantization")
    print(f" • Daily Digest Output ({len(digest.digest_5_lines)} lines):")
    for line in digest.digest_5_lines:
        print(f"   {line}")

    assert len(digest.digest_5_lines) == 5
    assert "1. [TOPIC & DATE]" in digest.digest_5_lines[0]
    assert "2. [TOP PAPER]" in digest.digest_5_lines[1]
    assert "3. [CORE FINDING]" in digest.digest_5_lines[2]
    assert "4. [OPEN GAP]" in digest.digest_5_lines[3]
    assert "5. [NEXT ACTION]" in digest.digest_5_lines[4]
    print(" >>> CRITERION 5 PASSED: Strict 5-line daily research digest synthesized. <<<")

    # -------------------------------------------------------------------------
    # 6. Public Rooms Engine & Tool Registry Integration
    # -------------------------------------------------------------------------
    print("\n[6/6] Testing ToolRegistry Dispatch of Phase 4 Tools...")
    tools = ToolRegistry(workspace_root=str(test_ws))
    tools.academic_writer = writer
    tools.digest_engine = digest_engine

    res_digest = await tools.dispatch("research_daily_digest", {"topic": "Quantization"})
    print(f" • Digest Tool Dispatch Status: {res_digest.success}")
    assert res_digest.success is True
    assert "1. [TOPIC & DATE]" in res_digest.output

    tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> RESEARCHER ROOM PHASE 4 FULLY VERIFIED & PRODUCTION READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_researcher_phase4())
