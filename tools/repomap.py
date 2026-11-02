import os
import ast
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from tools.system_tier import CURRENT_TIER, HardwareTier

class MultiLanguageASTParser:
    """
    Tier-adaptive parser providing full AST parsing for Python,
    tree-sitter/ctags for high tiers, and robust grammar extractors for
    JS/TS, Go, Rust, C/C++, and Java on edge/Termux.
    """

    # Language regex grammar patterns for non-Python code
    GRAMMAR_RULES: Dict[str, List[re.Pattern]] = {
        "javascript": [
            re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\([^)]*\)"),
            re.compile(r"^(?:export\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+[a-zA-Z0-9_$]+)?"),
            re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"),
        ],
        "typescript": [
            re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*(?:<[^>]+>)?\s*\([^)]*\)"),
            re.compile(r"^(?:export\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+implements\s+[^{]+)?"),
            re.compile(r"^(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)"),
            re.compile(r"^(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*="),
        ],
        "go": [
            re.compile(r"^func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\([^)]*\)"),
            re.compile(r"^type\s+([a-zA-Z0-9_]+)\s+struct"),
            re.compile(r"^type\s+([a-zA-Z0-9_]+)\s+interface"),
        ],
        "rust": [
            re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)"),
            re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?struct\s+([a-zA-Z0-9_]+)"),
            re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?enum\s+([a-zA-Z0-9_]+)"),
            re.compile(r"^impl(?:\s*<[^>]+>)?\s+([a-zA-Z0-9_]+)"),
        ],
        "cpp": [
            re.compile(r"^(?:[a-zA-Z0-9_:<>]+\s+)+([a-zA-Z0-9_]+)\s*\([^;)]*\)\s*(?:const)?\s*(?:override)?\s*\{?"),
            re.compile(r"^(?:class|struct)\s+([a-zA-Z0-9_]+)"),
        ],
        "java": [
            re.compile(r"^(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:[a-zA-Z0-9_<>\[\]]+\s+)+([a-zA-Z0-9_]+)\s*\([^)]*\)"),
            re.compile(r"^(?:public\s+)?(?:abstract\s+)?class\s+([a-zA-Z0-9_]+)"),
            re.compile(r"^(?:public\s+)?interface\s+([a-zA-Z0-9_]+)"),
        ],
    }

    EXTENSION_MAP = {
        ".py": "python",
        ".js": "javascript", ".mjs": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".h": "cpp",
        ".java": "java",
    }

    def parse_file(self, path: Path, limit: int = 15) -> List[str]:
        ext = path.suffix.lower()
        lang = self.EXTENSION_MAP.get(ext)
        if not lang:
            return []

        if lang == "python":
            return self._parse_python(path, limit)
        return self._parse_grammar(path, lang, limit)

    def _parse_python(self, path: Path, limit: int) -> List[str]:
        symbols = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(65536)
            tree = ast.parse(content, filename=str(path))
            for node in tree.body:
                if len(symbols) >= limit:
                    break
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    meth_str = f"({', '.join(methods[:3])})" if methods else ""
                    symbols.append(f"class {node.name}{meth_str}")
                elif isinstance(node, ast.FunctionDef):
                    args = [a.arg for a in node.args.args[:3]]
                    symbols.append(f"def {node.name}({', '.join(args)})")
        except Exception:
            # Fallback to regex if file has Python syntax errors
            return self._parse_grammar(path, "python", limit)
        return symbols

    def _parse_grammar(self, path: Path, lang: str, limit: int) -> List[str]:
        patterns = self.GRAMMAR_RULES.get(lang, [])
        if not patterns and lang == "python":
            patterns = [re.compile(r"^(?:class|def)\s+([a-zA-Z0-9_]+)")]

        symbols = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if len(symbols) >= limit:
                        break
                    s_line = line.strip()
                    for pat in patterns:
                        match = pat.search(s_line)
                        if match:
                            clean_sig = s_line.split("{")[0].strip().rstrip(":")
                            symbols.append(clean_sig)
                            break
        except Exception:
            pass
        return symbols


class RepoMapGenerator:
    """
    Tier-Dynamic Repository Map Generator supporting all major languages.
    """

    IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", "venv", ".venv",
        "build", "dist", "target", ".eggs", ".pytest_cache"
    }

    def __init__(self, max_tokens: Optional[int] = None):
        if max_tokens is not None:
            self.max_tokens = max_tokens
        else:
            self.max_tokens = 8192 if CURRENT_TIER == HardwareTier.TIER_HIGH else (2048 if CURRENT_TIER == HardwareTier.TIER_MID else 1024)

        self.max_chars = self.max_tokens * 4
        self.parser = MultiLanguageASTParser()
        self.has_ctags = shutil.which("ctags") is not None

    def generate(self, repo_dir: Path) -> str:
        if not repo_dir or not repo_dir.exists():
            return ""

        # High tier: use ctags when available for whole-repo symbol tables
        if CURRENT_TIER == HardwareTier.TIER_HIGH and self.has_ctags:
            map_str = self._generate_ctags(repo_dir)
            if map_str:
                return map_str

        return self._generate_multi_lang_ast(repo_dir)

    def _generate_multi_lang_ast(self, repo_dir: Path) -> str:
        lines: List[str] = []

        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith(".")]

            for file in files:
                if len("".join(lines)) >= self.max_chars:
                    break

                file_path = Path(root) / file
                symbols = self.parser.parse_file(file_path)
                if symbols:
                    rel_path = file_path.relative_to(repo_dir)
                    lines.append(f"{rel_path}:")
                    lines.extend(f"  {s}" for s in symbols)

        joined = "\n".join(lines)
        if CURRENT_TIER != HardwareTier.TIER_HIGH and len(joined) > self.max_chars:
            return joined[:self.max_chars] + "\n... [RepoMap compressed for context budget]"
        return joined

    def _generate_ctags(self, repo_dir: Path) -> str:
        try:
            cmd = ["ctags", "-R", "--output-format=json", "--fields=+n", "-f", "-", str(repo_dir)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            if res.returncode == 0 and res.stdout:
                import json
                out_lines = []
                for line in res.stdout.splitlines()[:250]:
                    tag = json.loads(line)
                    out_lines.append(f"{tag.get('path', '')}: {tag.get('kind', '')} {tag.get('name', '')}")
                return "\n".join(out_lines)
        except Exception:
            pass
        return ""
