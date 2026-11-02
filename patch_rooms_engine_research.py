from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add imports
research_imports = """from agent.pa_scaffolder.research_memory import (
    ResearchMemoryLayer, PaperRecord, ClaimRecord, ExperimentRecord, DeadEndRecord
)
from agent.pa_scaffolder.model_router import ModelAgnosticRouter, TaskProfile
"""
if "from agent.pa_scaffolder.research_memory import" not in code:
    code = research_imports + code

# 2. Add research memory and router instances to RoomsEngine.__init__
old_init = "self.tester_auditor = TesterAutonomousAuditor(self.workspace)"
new_init = old_init + """
        self.research_memory = ResearchMemoryLayer(db_path=self.workspace / "research_vault.db")
        self.model_router = ModelAgnosticRouter()"""

if old_init in code and "self.research_memory =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add execute_research_synthesis method to RoomsEngine
research_method = """    async def execute_research_synthesis(
        self,
        topic_query: str,
        profile: TaskProfile = TaskProfile.SKIM_EXTRACTION
    ) -> Dict[str, Any]:
        \"\"\"Public API: Runs literature lookup and model-agnostic synthesis in RESEARCHER mode.\"\"\"
        self.current_mode = AgentMode.RESEARCHER

        # 1. Search local memory
        local_papers = self.research_memory.search_papers(topic_query, limit=5)
        local_claims = self.research_memory.query_claims(topic_query, limit=5)
        dead_ends = self.research_memory.query_dead_ends(topic_query)

        # 2. Synthesize with task-routed model
        system_prompt = (
            "You are an elite scientific research specialist. Synthesize verified papers, "
            "highlight known dead-ends, and maintain strict citation grounding."
        )
        user_prompt = (
            f"Query: {topic_query}\\n"
            f"Indexed Papers: {json.dumps(local_papers)}\\n"
            f"Verified Claims: {json.dumps(local_claims)}\\n"
            f"Known Dead Ends: {json.dumps(dead_ends)}\\n"
        )

        router_resp = await self.model_router.dispatch_prompt(
            profile=profile,
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )

        return {
            "mode": AgentMode.RESEARCHER.value,
            "query": topic_query,
            "local_papers_count": len(local_papers),
            "dead_ends_detected": len(dead_ends),
            "synthesis": router_resp.content,
            "backend_used": router_resp.backend_used,
            "latency_sec": router_resp.latency_sec
        }
"""

if "def execute_research_synthesis" not in code:
    code = code + "\n" + research_method

target.write_text(code, encoding="utf-8")
print("[✓] Integrated ResearchMemoryLayer and ModelAgnosticRouter into rooms_engine.py.")
