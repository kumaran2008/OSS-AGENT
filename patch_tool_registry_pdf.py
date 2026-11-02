from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add dispatch handler
old_dispatch = '            if tool_name == "literature_search":'
new_dispatch = """            if tool_name == "literature_ingest_pdf":
                source = args.get("source", "")
                res = await self.literature.ingest_full_paper_pdf(source)
                msg = f"Ingested '{res['title']}' ({res['sections_count']} sections, {res['equations_count']} equations, {res['tables_count']} tables) from {res['pdf_path']}"
                return ToolResult(tool_name=tool_name, success=True, output=msg)

            elif tool_name == "literature_search":"""

if "literature_ingest_pdf" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch)

# 2. Add tool schema
old_schema = '            {"type": "function", "function": {"name": "literature_search",'
new_schema = """            {"type": "function", "function": {"name": "literature_ingest_pdf", "description": "Downloads and extracts full binary arXiv PDF with formulas and tables into research memory", "parameters": {"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]}}},
            {"type": "function", "function": {"name": "literature_search","""

if "literature_ingest_pdf" not in code and old_schema in code:
    code = code.replace(old_schema, new_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered literature_ingest_pdf tool in tool_registry.py")
