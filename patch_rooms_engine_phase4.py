from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add Phase 4 imports
phase4_imports = """from agent.pa_scaffolder.academic_writer import AcademicWriterEngine, ManuscriptDraft, BibtexReconciliationResult
from agent.pa_scaffolder.research_digest import ResearchDigestEngine, DailyResearchDigest
"""
if "from agent.pa_scaffolder.academic_writer import" not in code:
    code = phase4_imports + code

# 2. Add instances to RoomsEngine.__init__
old_init = "self.experiment_runner = SandboxedExperimentRunner(self.workspace, self.research_memory, self.math_verifier)"
new_init = old_init + """
        self.academic_writer = AcademicWriterEngine(self.research_memory)
        self.digest_engine = ResearchDigestEngine(self.research_memory, self.literature_engine)"""

if old_init in code and "self.academic_writer =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add public orchestration methods to RoomsEngine
phase4_methods = """
    def draft_research_manuscript(
        self,
        title: str,
        authors: List[str],
        sections: Dict[str, str],
        output_rel_dir: str = "docs/manuscript"
    ) -> Dict[str, Any]:
        \"\"\"Drafts complete LaTeX manuscript with reconciled BibTeX references.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        out_path = self.workspace / output_rel_dir
        draft = self.academic_writer.draft_manuscript(title, authors, sections, out_path)
        return asdict(draft)

    def generate_daily_research_digest(self, topic: str) -> Dict[str, Any]:
        \"\"\"Generates a strict 5-line daily research tracking digest.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        digest = self.digest_engine.generate_5_line_digest(topic)
        return asdict(digest)
"""

if "def draft_research_manuscript" not in code:
    code = code + "\n" + phase4_methods

target.write_text(code, encoding="utf-8")
print("[✓] Integrated AcademicWriterEngine and ResearchDigestEngine into rooms_engine.py")
