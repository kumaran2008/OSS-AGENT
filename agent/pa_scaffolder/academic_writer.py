import re
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set

from agent.pa_scaffolder.research_memory import ResearchMemoryLayer, PaperRecord


@dataclass
class BibtexReconciliationResult:
    is_valid: bool
    cited_keys: List[str]
    resolved_keys: List[str]
    missing_keys: List[str]
    reconciled_bibtex: str
    diagnostics: str


@dataclass
class ManuscriptDraft:
    title: str
    tex_content: str
    bib_content: str
    sections_count: int
    tables_count: int
    equations_count: int
    output_dir: str


class AcademicWriterEngine:
    """
    Academic Paper & LaTeX Generation Suite:
    - Extracts and reconciles \\cite{...} keys against memory to prevent compilation crashes.
    - Generates publication-ready LaTeX with converted tables and numbered equations.
    - Synthesizes point-by-point reviewer rebuttal templates.
    """

    def __init__(self, memory: ResearchMemoryLayer):
        self.memory = memory

    # -------------------------------------------------------------------------
    # 1. BibTeX Reconciliation & Citation Grounding
    # -------------------------------------------------------------------------
    @staticmethod
    def extract_cite_keys(tex_or_md_content: str) -> List[str]:
        """Extracts citation keys from \\cite{...}, \\citep{...}, and \\citet{...}."""
        raw_matches = re.findall(r'\\cite[pt]?\{([^}]+)\}', tex_or_md_content)
        keys: Set[str] = set()
        for match in raw_matches:
            for k in match.split(','):
                clean_k = k.strip()
                if clean_k:
                    keys.add(clean_k)
        return sorted(list(keys))

    def generate_bibtex_entry(self, paper: PaperRecord, fallback_key: Optional[str] = None) -> str:
        """Constructs a canonical, valid BibTeX entry for a paper."""
        if paper.bibtex and paper.bibtex.strip().startswith("@"):
            if fallback_key:
                clean_bib = re.sub(r'(@\w+\s*\{)\s*[^,]+,', rf'\g<1>{fallback_key},', paper.bibtex.strip(), count=1)
                return clean_bib
            return paper.bibtex.strip()

        first_author = paper.authors[0].split()[-1].lower() if paper.authors else "author"
        first_author = re.sub(r'[^a-z0-9]', '', first_author)
        key = fallback_key or f"{first_author}{paper.year}"

        authors_str = " and ".join(paper.authors) if paper.authors else "Unknown"
        venue = paper.venue or "arXiv preprint"

        bibtex = [
            f"@article{{{key},",
            f"  title = {{{paper.title}}},",
            f"  author = {{{authors_str}}},",
            f"  journal = {{{venue}}},",
            f"  year = {{{paper.year}}},",
            f"  eprint = {{{paper.paper_id}}}"
        ]
        if paper.pdf_path:
            bibtex.append(f"  url = {{{paper.pdf_path}}}")
        bibtex.append("}")
        return "\n".join(bibtex)

    def reconcile_bibtex(self, manuscript_text: str, custom_bibtex: Optional[str] = None) -> BibtexReconciliationResult:
        """
        Ensures 100% citation grounding:
        - Scans all \\cite{key} tags in manuscript.
        - Resolves keys against local research memory via exact key, author+year, or title.
        - Produces a deduplicated references.bib file and flags phantom keys.
        """
        cited_keys = self.extract_cite_keys(manuscript_text)
        resolved_keys: List[str] = []
        missing_keys: List[str] = []
        bib_entries: Dict[str, str] = {}

        # 1. Index any pre-existing custom bibtex entries
        if custom_bibtex:
            custom_matches = re.findall(r'@\w+\s*\{\s*([^,\s]+),', custom_bibtex)
            for k in custom_matches:
                bib_entries[k] = custom_bibtex

        # 2. Match cited keys against papers in memory
        with self.memory._get_connection() as conn:
            cur = conn.cursor()
            for key in cited_keys:
                if key in bib_entries:
                    resolved_keys.append(key)
                    continue

                row = None
                # Strategy 1: Match directly in bibtex or paper_id
                cur.execute("SELECT * FROM papers WHERE bibtex LIKE ? OR paper_id = ? OR paper_id LIKE ? LIMIT 1;", (f"%{key}%", key, f"%{key}%"))
                row = cur.fetchone()

                # Strategy 2: Extract Author surname + Year (e.g. chen2025 -> surname 'chen', year 2025)
                if not row:
                    m = re.match(r'^([a-zA-Z]+)(\d{2,4})', key)
                    if m:
                        surname = m.group(1)
                        yr_val = int(m.group(2))
                        if yr_val < 100:
                            yr_val += 2000
                        cur.execute("SELECT * FROM papers WHERE authors_json LIKE ? AND year = ? LIMIT 1;", (f"%{surname}%", yr_val))
                        row = cur.fetchone()

                # Strategy 3: General author or title match
                if not row:
                    m = re.match(r'^([a-zA-Z]+)', key)
                    surname = m.group(1) if m else key
                    cur.execute("SELECT * FROM papers WHERE authors_json LIKE ? OR title LIKE ? LIMIT 1;", (f"%{surname}%", f"%{surname}%"))
                    row = cur.fetchone()

                if row:
                    paper = PaperRecord(
                        paper_id=row["paper_id"],
                        title=row["title"],
                        authors=json.loads(row["authors_json"]),
                        year=row["year"],
                        venue=row["venue"],
                        abstract=row["abstract"],
                        pdf_path=row["pdf_path"],
                        bibtex=row["bibtex"],
                        citation_count=row["citation_count"]
                    )
                    bib_entries[key] = self.generate_bibtex_entry(paper, fallback_key=key)
                    resolved_keys.append(key)
                else:
                    missing_keys.append(key)

        is_valid = (len(missing_keys) == 0)
        reconciled_bib = "\n\n".join(bib_entries.values())
        diag = "All citations resolved." if is_valid else f"Missing {len(missing_keys)} citation(s): {missing_keys}"

        return BibtexReconciliationResult(
            is_valid=is_valid,
            cited_keys=cited_keys,
            resolved_keys=resolved_keys,
            missing_keys=missing_keys,
            reconciled_bibtex=reconciled_bib,
            diagnostics=diag
        )

    # -------------------------------------------------------------------------
    # 2. Markdown to LaTeX Conversion (Tables & Equations)
    # -------------------------------------------------------------------------
    @staticmethod
    def markdown_table_to_latex(md_table: str, caption: str = "Experimental Results", label: str = "tab:results") -> str:
        """Converts Markdown pipe tables into centered LaTeX tables."""
        lines = [line.strip() for line in md_table.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            return md_table

        def split_row(row_str: str) -> List[str]:
            cols = [c.strip() for c in row_str.split("|")]
            if cols and cols[0] == "":
                cols = cols[1:]
            if cols and cols[-1] == "":
                cols = cols[:-1]
            return cols

        headers = split_row(lines[0])
        data_rows = [split_row(r) for r in lines[2:]]

        col_align = "c" * len(headers)
        tex = [
            "\\begin{table}[h]",
            "  \\centering",
            f"  \\caption{{{caption}}}",
            f"  \\label{{{label}}}",
            f"  \\begin{{tabular}}{{{col_align}}}",
            "    \\hline",
            "    " + " & ".join(headers) + " \\\\",
            "    \\hline"
        ]
        for row in data_rows:
            padded = row + [""] * (len(headers) - len(row))
            tex.append("    " + " & ".join(padded[:len(headers)]) + " \\\\")
        tex.extend([
            "    \\hline",
            "  \\end{tabular}",
            "\\end{table}"
        ])
        return "\n".join(tex)

    @classmethod
    def convert_markdown_to_latex(cls, md_content: str) -> Tuple[str, int, int]:
        """Converts markdown headers, tables, and math equations into LaTeX."""
        text = md_content
        tables_count = 0
        equations_count = 0

        # 1. Convert Display Equations: $$...$$ to \begin{equation}...\end{equation}
        def eq_replacer(match):
            nonlocal equations_count
            equations_count += 1
            eq_body = match.group(1).strip()
            return f"\n\\begin{{equation}}\n  {eq_body}\n\\end{{equation}}\n"

        text = re.sub(r"\$\$(.*?)\$\$", eq_replacer, text, flags=re.DOTALL)

        # 2. Convert Markdown Tables
        table_blocks = re.findall(r"((?:\|[^\n]+\|\n?){2,})", text)
        for idx, tbl in enumerate(table_blocks, 1):
            tables_count += 1
            latex_tbl = cls.markdown_table_to_latex(tbl, caption=f"Evaluation Benchmark {idx}", label=f"tab:benchmark_{idx}")
            text = text.replace(tbl, "\n" + latex_tbl + "\n")

        # 3. Convert Markdown Headings
        text = re.sub(r"^### (.*?)$", r"\\subsubsection{\1}", text, flags=re.MULTILINE)
        text = re.sub(r"^## (.*?)$", r"\\subsection{\1}", text, flags=re.MULTILINE)
        text = re.sub(r"^# (.*?)$", r"\\section{\1}", text, flags=re.MULTILINE)

        # 4. Bold and Italics
        text = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", text)
        text = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", text)

        return text, tables_count, equations_count

    # -------------------------------------------------------------------------
    # 3. Full Manuscript Drafting
    # -------------------------------------------------------------------------
    def draft_manuscript(
        self,
        title: str,
        authors: List[str],
        sections: Dict[str, str],
        output_dir: Path
    ) -> ManuscriptDraft:
        output_dir.mkdir(parents=True, exist_ok=True)
        authors_tex = " \\and ".join(authors)

        combined_body = []
        total_tables = 0
        total_eqs = 0

        for sec_title, sec_md in sections.items():
            converted, t_count, e_count = self.convert_markdown_to_latex(sec_md)
            total_tables += t_count
            total_eqs += e_count
            if sec_title.lower() == "abstract":
                combined_body.append(f"\\begin{{abstract}}\n{converted.strip()}\n\\end{{abstract}}\n")
            else:
                combined_body.append(f"\\section{{{sec_title}}}\n{converted.strip()}\n")

        full_body = "\n".join(combined_body)
        recon = self.reconcile_bibtex(full_body)

        doc = [
            "\\documentclass[11pt,a4paper]{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts}",
            "\\usepackage{booktabs,tabularx}",
            "\\usepackage{hyperref}",
            "\\usepackage{cite}",
            "",
            f"\\title{{{title}}}",
            f"\\author{{{authors_tex}}}",
            "\\date{\\today}",
            "",
            "\\begin{document}",
            "\\maketitle",
            "",
            full_body,
            "",
            "\\bibliographystyle{plain}",
            "\\bibliography{references}",
            "\\end{document}"
        ]
        tex_source = "\n".join(doc)

        (output_dir / "main.tex").write_text(tex_source, encoding="utf-8")
        (output_dir / "references.bib").write_text(recon.reconciled_bibtex, encoding="utf-8")

        return ManuscriptDraft(
            title=title,
            tex_content=tex_source,
            bib_content=recon.reconciled_bibtex,
            sections_count=len(sections),
            tables_count=total_tables,
            equations_count=total_eqs,
            output_dir=str(output_dir)
        )

    # -------------------------------------------------------------------------
    # 4. Reviewer Rebuttal Generator
    # -------------------------------------------------------------------------
    @staticmethod
    def generate_reviewer_rebuttal(paper_title: str, review_items: List[Dict[str, str]]) -> str:
        rebuttal = [
            f"# AUTHOR RESPONSE & REBUTTAL: {paper_title.upper()}",
            "We thank the reviewers for their insightful and constructive feedback. Below is our point-by-point response.",
            ""
        ]
        for idx, item in enumerate(review_items, 1):
            reviewer = item.get("reviewer", "Reviewer")
            comment = item.get("comment", "")
            response = item.get("response", "We have clarified this in the revised manuscript.")
            diff = item.get("revision_diff", "")

            rebuttal.extend([
                f"### {reviewer} - Comment {idx}",
                f"> **Reviewer Point:** \"{comment}\"",
                "",
                f"**Author Response:** {response}",
                ""
            ])
            if diff:
                rebuttal.extend([
                    "**Manuscript Revision:**",
                    "```diff",
                    diff.strip(),
                    "```",
                    ""
                ])

        return "\n".join(rebuttal)
