from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add LiteratureEngine import
if "from agent.pa_scaffolder.literature_engine import LiteratureEngine" not in code:
    code = "from agent.pa_scaffolder.literature_engine import LiteratureEngine, RankedPaperImpact\n" + code

# 2. Add literature_engine instance to RoomsEngine.__init__
old_init = "self.model_router = ModelAgnosticRouter()"
new_init = old_init + "\n        self.literature_engine = LiteratureEngine(self.research_memory)"

if old_init in code and "self.literature_engine =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add public orchestration methods to RoomsEngine
literature_methods = """
    async def search_academic_literature(self, query: str, limit_per_source: int = 3) -> List[Dict[str, Any]]:
        \"\"\"Searches arXiv, Semantic Scholar, and OpenAlex in parallel with deduplication.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        results = await self.literature_engine.search_and_deduplicate(query, limit_per_source=limit_per_source)
        # Ingest discovered papers into persistent shared SQLite WAL memory
        for r in results:
            self.research_memory.store_paper(PaperRecord(
                paper_id=r.paper_id,
                title=r.title,
                authors=r.authors,
                year=r.year,
                venue=r.venue,
                abstract=r.abstract,
                pdf_path=r.pdf_url,
                citation_count=r.citation_count
            ))
        return [asdict(r) for r in results]

    def rank_influential_papers(self, topic_query: str) -> List[Dict[str, Any]]:
        \"\"\"Runs time-decayed PageRank on the citation graph to isolate the top 5 papers that matter.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        local_papers = self.research_memory.search_papers(topic_query, limit=12)

        # Retrieve citation edges from memory
        edges = []
        with self.research_memory._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT source_paper_id, target_paper_id FROM citation_graph;")
            edges = [(r[0], r[1]) for r in cur.fetchall()]

        ranked = self.literature_engine.compute_citation_impact_ranking(local_papers, edges)
        return [asdict(rp) for rp in ranked[:5]]
"""

if "def search_academic_literature" not in code:
    code = code + "\n" + literature_methods

target.write_text(code, encoding="utf-8")
print("[✓] Integrated LiteratureEngine into rooms_engine.py")
