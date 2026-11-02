from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.native import native_accel
from agent.pa_scaffolder.repo_symbol_mapper import PolyglotLexicalParser, RepoSymbolMapper


@dataclass
class IndexedSymbolNode:
    symbol_id: str
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    calls: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    source_slice: str = ""


class RepositoryIntelligenceEngine:
    """Section 5.2 & 5.3: Polyglot Repository Indexing, Call Graph & Adaptive Context Slicing."""

    SUPPORTED_EXTS = {".py", ".js", ".ts", ".tsx", ".html", ".css", ".c", ".h", ".cpp", ".go", ".rs"}

    def __init__(self):
        self._file_hash_cache: Dict[str, str] = {}
        self._file_symbols: Dict[str, List[IndexedSymbolNode]] = {}
        self._file_summaries: Dict[str, str] = {}
        self.polyglot_parser = PolyglotLexicalParser()
        self.symbol_mapper = RepoSymbolMapper(Path.cwd())

    def index_repository(self, root_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
        targets = root_dirs or ["agent/kernel", "agent/plugins", "agent/memory_graph", "agent/suites"]
        total_files = 0
        cache_hits = 0
        total_symbols = 0

        for rdir in targets:
            rp = Path(rdir)
            if not rp.exists():
                continue
            for fpath in sorted(rp.rglob("*")):
                if not fpath.is_file() or fpath.suffix.lower() not in self.SUPPORTED_EXTS:
                    continue
                if "__pycache__" in fpath.parts or ".shadow" in str(fpath):
                    continue
                total_files += 1
                rel_p = str(fpath)
                raw_bytes = fpath.read_bytes()
                f_hash = native_accel.fast_hash64_hex(raw_bytes)

                if self._file_hash_cache.get(rel_p) == f_hash and rel_p in self._file_symbols:
                    cache_hits += 1
                    total_symbols += len(self._file_symbols[rel_p])
                    continue

                src = raw_bytes.decode("utf-8", errors="replace")
                lines = src.splitlines()
                nodes: List[IndexedSymbolNode] = []
                file_imports: List[str] = []

                if fpath.suffix.lower() == ".py":
                    try:
                        tree = ast.parse(src)
                        for n in ast.walk(tree):
                            if isinstance(n, ast.Import):
                                file_imports.extend(a.name for a in n.names)
                            elif isinstance(n, ast.ImportFrom) and n.module:
                                file_imports.append(n.module)

                        for node in tree.body:
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                s_ln = node.lineno
                                e_ln = getattr(node, "end_lineno", s_ln + 12)
                                calls = [
                                    c.func.id for c in ast.walk(node)
                                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                                ]
                                sig_ln = lines[s_ln - 1].strip() if s_ln - 1 < len(lines) else node.name
                                kind = "class" if isinstance(node, ast.ClassDef) else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
                                nodes.append(
                                    IndexedSymbolNode(
                                        symbol_id=f"{rel_p}::{node.name}",
                                        name=node.name,
                                        kind=kind,
                                        file_path=rel_p,
                                        start_line=s_ln,
                                        end_line=e_ln,
                                        signature=sig_ln,
                                        calls=sorted(set(calls)),
                                        imports=sorted(set(file_imports)),
                                        source_slice="\n".join(lines[max(0, s_ln - 1) : min(len(lines), e_ln)]),
                                    )
                                )
                    except Exception:
                        pass
                else:
                    # Non-Python polyglot indexing via PolyglotLexicalParser + regex fallback
                    try:
                        lex_syms = self.polyglot_parser.extract_symbols(src, fpath.suffix.lower())
                        for ls in lex_syms:
                            s_ln = getattr(ls, "line", 1)
                            nodes.append(
                                IndexedSymbolNode(
                                    symbol_id=f"{rel_p}::{ls.name}",
                                    name=ls.name,
                                    kind=getattr(ls, "kind", "symbol"),
                                    file_path=rel_p,
                                    start_line=s_ln,
                                    end_line=min(len(lines), s_ln + 15),
                                    signature=getattr(ls, "signature", ls.name),
                                    source_slice="\n".join(lines[max(0, s_ln - 1) : min(len(lines), s_ln + 15)]),
                                )
                            )
                    except Exception:
                        for m in re.finditer(r"(?:function|class|const|let|fn|func)\s+([a-zA-Z0-9_]+)", src):
                            nm = m.group(1)
                            nodes.append(
                                IndexedSymbolNode(
                                    symbol_id=f"{rel_p}::{nm}",
                                    name=nm,
                                    kind="polyglot_symbol",
                                    file_path=rel_p,
                                    start_line=1,
                                    end_line=min(len(lines), 20),
                                    signature=nm,
                                    source_slice="\n".join(lines[:20]),
                                )
                            )

                self._file_hash_cache[rel_p] = f_hash
                self._file_symbols[rel_p] = nodes
                sym_names = ", ".join(f"{n.kind}:{n.name}" for n in nodes[:12])
                self._file_summaries[rel_p] = f"{rel_p} ({len(lines)} lines) -> [{sym_names}]"
                total_symbols += len(nodes)

        return {
            "files_indexed": total_files,
            "change_aware_cache_hits": cache_hits,
            "total_symbols": total_symbols,
        }

    def retrieve_adaptive_context(
        self,
        task_query: str,
        root_dirs: Optional[List[str]] = None,
        cross_cutting_refactor: bool = False,
    ) -> Dict[str, Any]:
        idx_stats = self.index_repository(root_dirs)
        all_files = list(self._file_summaries.keys())
        baseline_chars = sum(sum(len(s.source_slice) for s in syms) + 200 for syms in self._file_symbols.values())
        baseline_tokens = max(1, baseline_chars // 4)

        file_scores = [
            (fp, jev_ai_brain.compute_semantic_alignment(task_query, summary))
            for fp, summary in self._file_summaries.items()
        ]
        file_scores.sort(key=lambda x: x[1], reverse=True)
        max_files = 12 if cross_cutting_refactor else 4
        selected_files = [fp for fp, sc in file_scores[:max_files] if sc > 0.0] or all_files[:2]

        selected_symbols: List[IndexedSymbolNode] = []
        target_symbol_names: Set[str] = set()
        for fp in selected_files:
            for sym in self._file_symbols.get(fp, []):
                align = jev_ai_brain.compute_semantic_alignment(task_query, f"{sym.name} {sym.signature} {sym.source_slice[:300]}")
                if align >= 0.15 or cross_cutting_refactor or len(selected_symbols) < 3:
                    selected_symbols.append(sym)
                    target_symbol_names.add(sym.name)

        caller_symbols: List[IndexedSymbolNode] = []
        for fp, syms in self._file_symbols.items():
            for sym in syms:
                if sym not in selected_symbols and target_symbol_names.intersection(sym.calls):
                    caller_symbols.append(sym)

        final_symbols = selected_symbols + caller_symbols[:6]
        assembled_context = "\n\n".join(
            f"# File: {s.file_path} (Lines {s.start_line}-{s.end_line})\n{s.source_slice}"
            for s in final_symbols
        )
        compressed_tokens = max(1, native_accel.estimate_tokens(assembled_context))
        savings_pct = round(max(0.0, (1.0 - (compressed_tokens / max(1, baseline_tokens))) * 100.0), 1)

        return {
            "files_indexed": idx_stats["files_indexed"],
            "change_aware_cache_hits": idx_stats["change_aware_cache_hits"],
            "selected_files": selected_files,
            "selected_symbols": [s.symbol_id for s in final_symbols],
            "dependency_callers_included": len(caller_symbols[:6]),
            "baseline_repo_tokens": baseline_tokens,
            "retrieved_context_tokens": compressed_tokens,
            "token_savings_percent": savings_pct,
            "assembled_context": assembled_context,
        }


repo_intelligence = RepositoryIntelligenceEngine()
