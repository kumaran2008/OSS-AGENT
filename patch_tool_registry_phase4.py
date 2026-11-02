from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add imports
phase4_imports = """from agent.pa_scaffolder.academic_writer import AcademicWriterEngine
from agent.pa_scaffolder.research_digest import ResearchDigestEngine
"""
if "from agent.pa_scaffolder.academic_writer import" not in code:
    code = phase4_imports + code

# 2. Add instances to ToolRegistry.__init__
old_init = "self.experiment_runner = SandboxedExperimentRunner(self.workspace_root, self.research_memory, self.math_verifier)"
new_init = old_init + """
        self.academic_writer = AcademicWriterEngine(self.research_memory)
        self.digest_engine = ResearchDigestEngine(self.research_memory, self.literature)"""

if old_init in code and "self.academic_writer =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add dispatch handlers
old_dispatch = '            # -----------------------------------------------------------------\n            # Math, Statistics & Sandboxed Experiment Tools'
new_dispatch = """            # -----------------------------------------------------------------
            # Academic Writing, BibTeX & Daily Digest Tools
            # -----------------------------------------------------------------
            if tool_name == "writer_reconcile_bibtex":
                txt = args.get("manuscript_text", "")
                recon = self.academic_writer.reconcile_bibtex(txt)
                return ToolResult(tool_name=tool_name, success=recon.is_valid, output=recon.reconciled_bibtex, error=None if recon.is_valid else recon.diagnostics)

            elif tool_name == "writer_draft_manuscript":
                title = args.get("title", "Research Manuscript")
                authors = args.get("authors", ["Author et al."])
                sections = args.get("sections", {})
                out_dir = self.workspace_root / args.get("output_dir", "docs/manuscript")
                draft = self.academic_writer.draft_manuscript(title, authors, sections, out_dir)
                msg = f"Drafted '{draft.title}' with {draft.tables_count} tables and {draft.equations_count} equations in {draft.output_dir}"
                return ToolResult(tool_name=tool_name, success=True, output=msg)

            elif tool_name == "research_daily_digest":
                topic = args.get("topic", "Machine Learning")
                digest = self.digest_engine.generate_5_line_digest(topic)
                return ToolResult(tool_name=tool_name, success=True, output=digest.raw_markdown)

"""

if "writer_reconcile_bibtex" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch + old_dispatch)

# 4. Add schemas to get_all_tool_schemas
old_schema = '            {"type": "function", "function": {"name": "math_verify_derivation",'
new_schemas = """            {"type": "function", "function": {"name": "writer_reconcile_bibtex", "description": "Reconciles manuscript citations against research memory and outputs clean references.bib", "parameters": {"type": "object", "properties": {"manuscript_text": {"type": "string"}}, "required": ["manuscript_text"]}}},
            {"type": "function", "function": {"name": "writer_draft_manuscript", "description": "Generates complete publication LaTeX document with tables and equations", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "sections": {"type": "object"}}, "required": ["title", "sections"]}}},
            {"type": "function", "function": {"name": "research_daily_digest", "description": "Generates strict 5-line daily research tracking digest for a topic", "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}},
"""

if "writer_reconcile_bibtex" not in code and old_schema in code:
    code = code.replace(old_schema, new_schemas + old_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered Phase 4 tools in tool_registry.py")
