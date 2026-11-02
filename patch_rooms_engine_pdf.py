from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

pdf_method = """    async def ingest_arxiv_paper(self, arxiv_id_or_url: str) -> Dict[str, Any]:
        \"\"\"Downloads full arXiv binary PDF, extracts layout/math/tables, and stores in memory.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        return await self.literature_engine.ingest_full_paper_pdf(arxiv_id_or_url)
"""

if "def ingest_arxiv_paper" not in code:
    code = code + "\n" + pdf_method
    target.write_text(code, encoding="utf-8")
    print("[✓] Added ingest_arxiv_paper to rooms_engine.py")
else:
    print("[i] ingest_arxiv_paper already present in rooms_engine.py")
