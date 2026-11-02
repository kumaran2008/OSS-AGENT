from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add LiteratureEngine import
if "from agent.pa_scaffolder.literature_engine import LiteratureEngine" not in code:
    code = "from agent.pa_scaffolder.literature_engine import LiteratureEngine\n" + code

# 2. Add literature engine to ToolRegistry.__init__
old_init = "self.tester = TesterAutonomousAuditor(self.workspace_root)"
new_init = old_init + """
        from agent.pa_scaffolder.research_memory import ResearchMemoryLayer
        self.research_memory = ResearchMemoryLayer(db_path=self.workspace_root / "research_vault.db")
        self.literature = LiteratureEngine(self.research_memory)"""

if old_init in code and "self.literature =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add dispatch handlers
old_dispatch = '            # -----------------------------------------------------------------\n            # Tester Room Specialized QA Tools'
new_dispatch = """            # -----------------------------------------------------------------
            # Literature & Academic Research Tools
            # -----------------------------------------------------------------
            if tool_name == "literature_search":
                q = args.get("query", "")
                limit = int(args.get("limit_per_source", 3))
                hits = await self.literature.search_and_deduplicate(q, limit_per_source=limit)
                out = [f"• [{h.source.upper()}] {h.title} ({h.year}) - Citations: {h.citation_count}" for h in hits]
                return ToolResult(tool_name=tool_name, success=True, output="\\n".join(out) if out else "No papers found.")

            elif tool_name == "literature_rank_papers":
                q = args.get("query", "")
                papers = self.research_memory.search_papers(q, limit=10)
                ranked = self.literature.compute_citation_impact_ranking(papers, [])
                out = [f"• {r.archetype.upper()}: {r.title} ({r.year}) | Impact: {r.composite_impact_score}" for r in ranked[:5]]
                return ToolResult(tool_name=tool_name, success=True, output="\\n".join(out) if out else "No papers indexed.")

"""

if "literature_search" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch + old_dispatch)

# 4. Add schemas to get_all_tool_schemas
old_schema = '            {"type": "function", "function": {"name": "tester_run_suite",'
new_schema = """            {"type": "function", "function": {"name": "literature_search", "description": "Searches arXiv, Semantic Scholar, and OpenAlex in parallel with deduplication", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit_per_source": {"type": "integer"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "literature_rank_papers", "description": "Ranks papers using time-decayed PageRank to isolate the 5 that matter", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
"""

if "literature_search" not in code and old_schema in code:
    code = code.replace(old_schema, new_schema + old_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered literature_search and literature_rank_papers in tool_registry.py")
