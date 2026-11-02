import zlib
import time
import shutil
import asyncio
from pathlib import Path

from agent.pa_scaffolder.research_memory import ResearchMemoryLayer
from agent.pa_scaffolder.literature_engine import LiteratureEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


def create_mock_binary_pdf(output_path: Path):
    """
    Generates a valid binary PDF with FlateDecode streams containing
    title, academic sections, LaTeX display equations, and markdown tables.
    """
    pdf_content = (
        "Sub-Quadratic Quantization for Billion-Token Context Models\n\n"
        "Abstract\n"
        "We present Sub-Quadratic Quantization for billion-token context models.\n\n"
        "1. Introduction\n"
        "Memory bandwidth in modern attention projections represents a major bottleneck.\n\n"
        "3. Methodology\n"
        "We define our low-rank dynamic projection as follows:\n"
        "$$A_{i,j} = \\frac{\\exp(Q_i K_j^T / \\sqrt{d})}{\\sum_k \\exp(Q_i K_k^T / \\sqrt{d})}$$\n"
        "where key and value projections are non-uniformly quantized to FP8.\n\n"
        "4. Results\n"
        "Table 1 outlines performance benchmarks:\n"
        "| Architecture | Latency (ms) | Speedup |\n"
        "|---|---|---|\n"
        "| Baseline FP16 | 45.2 | 1.0x |\n"
        "| FP8 Non-Uniform | 26.1 | 1.73x |\n\n"
        "5. Limitations\n"
        "Quantization below 4-bits causes outlier scale divergence in intermediate layers.\n"
    )

    compressed_stream = zlib.compress(pdf_content.encode("utf-8"))
    stream_len = len(compressed_stream)

    pdf_bytes = bytearray()
    pdf_bytes.extend(b"%PDF-1.4\n")
    # Object 1: Catalog
    pdf_bytes.extend(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    # Object 2: Pages
    pdf_bytes.extend(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    # Object 3: Page
    pdf_bytes.extend(b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n")
    # Object 4: Stream
    pdf_bytes.extend(f"4 0 obj\n<< /Length {stream_len} /Filter /FlateDecode >>\nstream\n".encode("utf-8"))
    pdf_bytes.extend(compressed_stream)
    pdf_bytes.extend(b"\nendstream\nendobj\n")
    pdf_bytes.extend(b"xref\n0 5\n0000000000 65535 f \ntrailer\n<< /Root 1 0 R >>\nstartxref\n500\n%%EOF\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(pdf_bytes))


async def test_binary_pdf_extractor():
    print("=" * 70)
    print("     GAP 1 VERIFICATION: BINARY PDF EXTRACTION ENGINE")
    print("=" * 70)

    test_ws = Path("workspace/test_pdf_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    db_path = test_ws / "test_vault.db"
    memory = ResearchMemoryLayer(db_path=db_path)
    engine = LiteratureEngine(memory_layer=memory, downloads_dir=test_ws / "downloads")

    # 1. Synthesize binary PDF
    sample_pdf_path = test_ws / "downloads" / "arxiv_2502.9999.pdf"
    create_mock_binary_pdf(sample_pdf_path)
    print(f"\n[1/4] Generated Binary PDF: {sample_pdf_path.name} ({sample_pdf_path.stat().st_size} bytes)")
    assert sample_pdf_path.exists()
    assert sample_pdf_path.stat().st_size > 100

    # 2. Extract Markdown via Multi-Tier Engine
    print("\n[2/4] Testing Multi-Tier Layout Extraction...")
    t0 = time.perf_counter()
    extracted_md = engine.extract_pdf_to_markdown(sample_pdf_path)
    t_extract_ms = (time.perf_counter() - t0) * 1000.0

    print(f" • Extraction Time:       {t_extract_ms:.2f} ms")
    print(f" • Extracted Length:      {len(extracted_md)} characters")
    assert "Methodology" in extracted_md
    assert "Results" in extracted_md
    assert "Table 1" in extracted_md
    print(" >>> CRITERION 1 PASSED: Binary PDF streams decompressed & extracted to Markdown. <<<")

    # 3. Layout Sectioning, Equations & Tables
    print("\n[3/4] Testing Academic Section & Formula Extraction...")
    sections = engine.parse_paper_layout_and_sections(extracted_md)
    sec_types = [s.section_type for s in sections]
    print(f" • Detected Sections:     {sec_types}")
    assert "abstract" in sec_types
    assert "methodology" in sec_types
    assert "results" in sec_types
    assert "limitations" in sec_types

    method_sec = next(s for s in sections if s.section_type == "methodology")
    print(f" • Equations Isolated:    {len(method_sec.equations)} (e.g., {method_sec.equations[0][:25]}...)")
    assert "$$A_{i,j}" in method_sec.equations[0]

    results_sec = next(s for s in sections if s.section_type == "results")
    print(f" • Tables Isolated:       {len(results_sec.tables)}")
    assert "| Baseline FP16 |" in results_sec.tables[0]
    print(" >>> CRITERION 2 PASSED: LaTeX display equations and Markdown tables preserved. <<<")

    # 4. Ingestion into SQLite WAL Memory & Tool Dispatch
    print("\n[4/4] Testing Tool Registry Dispatch & FTS5 Search Integration...")
    tools = ToolRegistry(workspace_root=str(test_ws))
    tools.literature = engine

    # Emulate download by pointing to the pre-generated binary file
    engine.download_pdf = lambda src: asyncio.sleep(0.01, result=sample_pdf_path)

    res_tool = await tools.dispatch("literature_ingest_pdf", {"source": "arxiv:2502.9999"})
    print(f" • Tool Dispatch Output:  \"{res_tool.output}\"")
    assert res_tool.success is True

    # Search FTS5 memory for content extracted from the binary PDF
    search_hits = memory.search_papers("billion-token", limit=5)
    print(f" • FTS5 Search Hits:      {len(search_hits)}")
    assert len(search_hits) >= 1
    assert "Sub-Quadratic" in search_hits[0]["title"] or "2502.9999" in search_hits[0]["paper_id"]
    print(f" • Top Search Hit Title:  \"{search_hits[0]['title']}\"")
    print(" >>> CRITERION 3 PASSED: Full binary PDF indexed in SQLite WAL FTS5 memory. <<<")

    tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> GAP 1 (BINARY PDF EXTRACTION ENGINE) 100% OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_binary_pdf_extractor())
