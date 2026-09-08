import ast
import re
from pathlib import Path
from typing import List, Dict, Optional

# Tree-sitter is optional. On Termux/Android, py-tree-sitter's compiled
# bindings frequently fail to build — this must never crash the import,
# only disable the tree-sitter path and fall back to regex.
try:
    import tree_sitter
    from tree_sitter_languages import get_language, get_parser
    TREE_SITTER_AVAILABLE = True
except Exception:
    TREE_SITTER_AVAILABLE = False


EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".go": "go",
    ".rs": "rust",
}

# Regex fallback patterns — used when tree-sitter is unavailable, or for
# any language tree-sitter doesn't have a grammar loaded for. Deliberately
# simple: this is a heuristic scanner, not a real parser, and is not
# expected to catch every edge case (generics, decorators split across
# lines, etc.) — it's a proportionate fallback, not a full parse.
REGEX_FUNCTION_PATTERNS = {
    "python": r'^\s*def\s+(\w+)\s*\(',
    "javascript": r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|'
                  r'^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(',
    "typescript": r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|'
                  r'^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(',
    "java": r'^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(',
    "c": r'^\s*[\w\*]+\s+(\w+)\s*\([^;]*\)\s*\{',
    "cpp": r'^\s*[\w:\*<>~]+\s+(\w+)\s*\([^;]*\)\s*\{',
    "go": r'^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(',
    "rust": r'^\s*(?:pub\s+)?fn\s+(\w+)\s*\(',
}


def detect_language(file_path: Path) -> Optional[str]:
    """Returns the detected language for a file, or None if unrecognized."""
    return EXTENSION_LANGUAGE_MAP.get(file_path.suffix.lower())


def _has_nearby_doc_comment(lines: List[str], func_line_index: int) -> bool:
    """
    Heuristic check: does a comment/docstring-like line appear immediately
    before this function definition? Checks up to 3 lines back for common
    comment markers such as //, #, /*, *, or triple-quote style strings.
    """
    comment_markers = ("//", "#", "/*", "*", '"""', "'''")
    for offset in range(1, 4):
        idx = func_line_index - offset
        if idx < 0:
            break
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if stripped.startswith(comment_markers):
            return True
        break  # hit a non-comment, non-blank line — stop looking further back
    return False


def _extract_with_tree_sitter(content: str, language: str) -> List[Dict]:
    """
    Extracts function definitions using tree-sitter, when available and
    a grammar is loaded for this language. Returns a list of
    {name, line, has_doc} dicts. Falls back silently (returns []) on any
    parse error — caller is responsible for falling back to regex.
    """
    try:
        parser = get_parser(language)
        tree = parser.parse(bytes(content, "utf8"))
    except Exception:
        return []

    results = []
    lines = content.splitlines()

    # Node type names vary per grammar; check the common ones across
    # supported languages rather than a single universal type.
    function_node_types = {
        "function_definition", "function_declaration", "method_declaration",
        "function_item", "method_definition", "arrow_function",
    }

    def walk(node):
        if node.type in function_node_types:
            name = None
            for child in node.children:
                if child.type in ("identifier", "property_identifier", "field_identifier"):
                    name = content[child.start_byte:child.end_byte]
                    break
            line_no = node.start_point[0]
            has_doc = _has_nearby_doc_comment(lines, line_no)
            results.append({"name": name or "<anonymous>", "line": line_no + 1, "has_doc": has_doc})
        for child in node.children:
            walk(child)

    try:
        walk(tree.root_node)
    except Exception:
        return []

    return results


def _extract_with_regex(content: str, language: str) -> List[Dict]:
    """
    Extracts function definitions using a simple line-by-line regex scan.
    Used when tree-sitter is unavailable, or as a fallback for any
    language/file tree-sitter fails on. Heuristic, not exhaustive.
    """
    pattern = REGEX_FUNCTION_PATTERNS.get(language)
    if not pattern:
        return []

    compiled = re.compile(pattern)
    lines = content.splitlines()
    results = []

    for i, line in enumerate(lines):
        match = compiled.match(line)
        if match:
            name = next((g for g in match.groups() if g), "<anonymous>")
            has_doc = _has_nearby_doc_comment(lines, i)
            results.append({"name": name, "line": i + 1, "has_doc": has_doc})

    return results


def extract_functions(file_path: Path, content: str) -> List[Dict]:
    """
    Main entry point: extracts function definitions from a source file,
    each as {name, line, has_doc}. Tries tree-sitter first if available
    and the language is supported by it; falls back to regex on any
    failure or if tree-sitter isn't installed. Python files continue to
    use the stdlib ast module directly (see researcher.py), since that
    path is already exact and free — this module handles everything else.
    """
    language = detect_language(file_path)
    if not language:
        return []

    if TREE_SITTER_AVAILABLE:
        results = _extract_with_tree_sitter(content, language)
        if results:
            return results
        # Fall through to regex if tree-sitter found nothing (e.g. grammar
        # not loaded for this language, or the file failed to parse).

    return _extract_with_regex(content, language)
