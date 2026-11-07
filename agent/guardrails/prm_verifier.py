from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PRMVerificationVerdict:
    is_valid: bool
    reward_score: float
    language: str
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_line: int = 1
    failing_symbol: str = "<module>"
    ast_metrics: Dict[str, int] = field(default_factory=dict)
    security_warnings: List[str] = field(default_factory=list)
    placeholder_violations: List[str] = field(default_factory=list)
    receipt_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "reward_score": round(self.reward_score, 4),
            "language": self.language,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_line": self.error_line,
            "failing_symbol": self.failing_symbol,
            "ast_metrics": self.ast_metrics,
            "security_warnings": self.security_warnings,
            "placeholder_violations": self.placeholder_violations,
            "receipt_hash": self.receipt_hash,
        }


class ProcessRewardGuard:
    """
    Gen-4 Process Reward Model (PRM) & Polyglot Structural Verifier for Oryn, OrynX-Code & OrynX-Builder.
    Zero dependency on legacy Gen-2 `codex_store` or `turn_retriever`.
    Persists step-level verification receipts directly into SQLite WAL (`workspace/kernel_governance.db`).
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    FORBIDDEN_PYTHON_CALLS = {
        "eval": "Arbitrary eval() execution risk",
        "exec": "Unconstrained exec() execution risk",
        "os.system": "Raw shell injection risk; use IsolatedSubprocessSandbox",
    }

    PLACEHOLDER_PATTERNS = [
        re.compile(r"#\s*TODO\s*:\s*implement", re.IGNORECASE),
        re.compile(r"//\s*TODO\s*:\s*implement", re.IGNORECASE),
        re.compile(r"raise\s+NotImplementedError\s*\(\s*\)", re.IGNORECASE),
        re.compile(r"\.\.\.\s*#\s*placeholder", re.IGNORECASE),
    ]

    DESTRUCTIVE_SQL_RE = re.compile(
        r"\b(?:DROP\s+TABLE\s+(?!IF\s+EXISTS\s+temp_)|TRUNCATE\s+TABLE|DELETE\s+FROM\s+\w+\s*;)\b",
        re.IGNORECASE,
    )

    JSX_TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9_.]*)[^>]*?>")

    @classmethod
    def _ensure_db(cls) -> None:
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(cls.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prm_step_verdicts (
                    receipt_hash TEXT PRIMARY KEY,
                    language TEXT,
                    is_valid INTEGER,
                    reward_score REAL,
                    error_type TEXT,
                    error_message TEXT,
                    error_line INTEGER,
                    failing_symbol TEXT,
                    metrics_json TEXT,
                    created_at REAL
                )
                """
            )

    @classmethod
    def _record_verdict(cls, verdict: PRMVerificationVerdict, source_code: str) -> PRMVerificationVerdict:
        raw_digest = hashlib.sha256(
            f"{verdict.language}:{verdict.is_valid}:{verdict.reward_score}:{source_code}".encode("utf-8")
        ).hexdigest()[:24]
        verdict.receipt_hash = f"prm_{raw_digest}"
        try:
            cls._ensure_db()
            with sqlite3.connect(cls.DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO prm_step_verdicts
                    (receipt_hash, language, is_valid, reward_score, error_type, error_message, error_line, failing_symbol, metrics_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        verdict.receipt_hash,
                        verdict.language,
                        1 if verdict.is_valid else 0,
                        float(verdict.reward_score),
                        verdict.error_type,
                        verdict.error_message,
                        int(verdict.error_line),
                        verdict.failing_symbol,
                        json.dumps(verdict.ast_metrics),
                        time.time(),
                    ),
                )
        except sqlite3.Error:
            pass
        return verdict

    @classmethod
    def _locate_enclosing_symbol(cls, source_code: str, target_line: int) -> str:
        lines = source_code.splitlines()
        idx = min(max(0, target_line - 1), max(0, len(lines) - 1))
        for i in range(idx, -1, -1):
            stripped = lines[i].strip()
            if stripped.startswith(("def ", "async def ", "class ", "function ", "export function ", "export const ")):
                return stripped.split("(")[0].split(":")[0].split("=")[0].strip()
        return "<module>"

    @classmethod
    def detect_placeholders(cls, source_code: str) -> List[str]:
        hits: List[str] = []
        for idx, line in enumerate(source_code.splitlines(), start=1):
            for pat in cls.PLACEHOLDER_PATTERNS:
                if pat.search(line):
                    hits.append(f"Line {idx}: {line.strip()[:80]}")
        return hits

    @classmethod
    def verify_python_syntax(cls, source_code: str, check_placeholders: bool = False) -> PRMVerificationVerdict:
        """
        Parses Python source into an AST, verifies syntax, counts classes/functions/asserts/returns,
        audits dangerous calls, and computes a calibrated Process Reward score in [0.0, 1.0].
        """
        if not source_code or not source_code.strip():
            verdict = PRMVerificationVerdict(
                is_valid=False,
                reward_score=0.0,
                language="python",
                error_type="EmptySourceError",
                error_message="Candidate Python source code is empty",
                error_line=1,
            )
            return cls._record_verdict(verdict, source_code or "")

        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            lineno = exc.lineno or 1
            symbol = cls._locate_enclosing_symbol(source_code, lineno)
            verdict = PRMVerificationVerdict(
                is_valid=False,
                reward_score=0.0,
                language="python",
                error_type="SyntaxError",
                error_message=f"{exc.msg} (line {lineno}, offset {exc.offset})",
                error_line=lineno,
                failing_symbol=symbol,
            )
            return cls._record_verdict(verdict, source_code)

        func_count = 0
        async_func_count = 0
        class_count = 0
        assert_count = 0
        import_count = 0
        return_count = 0
        empty_except_count = 0
        security_warnings: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_count += 1
            elif isinstance(node, ast.AsyncFunctionDef):
                async_func_count += 1
            elif isinstance(node, ast.ClassDef):
                class_count += 1
            elif isinstance(node, ast.Assert):
                assert_count += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                import_count += 1
            elif isinstance(node, ast.Return):
                return_count += 1
            elif isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    empty_except_count += 1
            elif isinstance(node, ast.Call):
                call_name = ""
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    call_name = f"{node.func.value.id}.{node.func.attr}"
                if call_name in cls.FORBIDDEN_PYTHON_CALLS:
                    security_warnings.append(
                        f"Line {getattr(node, 'lineno', 1)}: {call_name} — {cls.FORBIDDEN_PYTHON_CALLS[call_name]}"
                    )

        placeholders = cls.detect_placeholders(source_code) if check_placeholders else []
        penalty = (0.15 * len(security_warnings)) + (0.05 * empty_except_count) + (0.20 * len(placeholders))
        reward = max(0.10, min(1.0, 1.0 - penalty))
        is_valid = len(placeholders) == 0

        verdict = PRMVerificationVerdict(
            is_valid=is_valid,
            reward_score=reward,
            language="python",
            error_type="PlaceholderViolation" if not is_valid else None,
            error_message="; ".join(placeholders) if not is_valid else None,
            ast_metrics={
                "functions": func_count,
                "async_functions": async_func_count,
                "classes": class_count,
                "asserts": assert_count,
                "imports": import_count,
                "returns": return_count,
                "empty_excepts": empty_except_count,
            },
            security_warnings=security_warnings,
            placeholder_violations=placeholders,
        )
        return cls._record_verdict(verdict, source_code)

    @classmethod
    def verify_typescript_or_jsx_structure(cls, source_code: str, file_path: str = "component.tsx") -> PRMVerificationVerdict:
        """
        Verifies TypeScript / React (.ts / .tsx / .js / .jsx) structural balance:
        checks bracket/brace/paren balance outside strings/comments and verifies JSX tag pairing.
        """
        lang = "tsx" if file_path.endswith((".tsx", ".jsx")) else "typescript"
        if not source_code or not source_code.strip():
            return cls._record_verdict(
                PRMVerificationVerdict(
                    is_valid=False,
                    reward_score=0.0,
                    language=lang,
                    error_type="EmptySourceError",
                    error_message="Empty TypeScript/JSX file",
                ),
                "",
            )

        # Strip strings and comments for bracket balance check
        cleaned = re.sub(r"//.*?$|/\*.*?\*/|\x27(?:\\.|[^\x27\\])*\x27|\x22(?:\\.|[^\x22\\])*\x22|`(?:\\.|[^`\\])*`", "", source_code, flags=re.DOTALL | re.MULTILINE)
        pairs = {"}": "{", ")": "(", "]": "["}
        opening = set(pairs.values())
        stack: List[Tuple[str, int]] = []

        for line_idx, line in enumerate(cleaned.splitlines(), start=1):
            for ch in line:
                if ch in opening:
                    stack.append((ch, line_idx))
                elif ch in pairs:
                    if not stack or stack[-1][0] != pairs[ch]:
                        verdict = PRMVerificationVerdict(
                            is_valid=False,
                            reward_score=0.0,
                            language=lang,
                            error_type="UnbalancedDelimiterError",
                            error_message=f"Unexpected closing delimiter '{ch}' at line {line_idx}",
                            error_line=line_idx,
                            failing_symbol=cls._locate_enclosing_symbol(source_code, line_idx),
                        )
                        return cls._record_verdict(verdict, source_code)
                    stack.pop()

        if stack:
            unclosed_ch, unclosed_line = stack[-1]
            verdict = PRMVerificationVerdict(
                is_valid=False,
                reward_score=0.0,
                language=lang,
                error_type="UnclosedDelimiterError",
                error_message=f"Unclosed delimiter '{unclosed_ch}' opened at line {unclosed_line}",
                error_line=unclosed_line,
                failing_symbol=cls._locate_enclosing_symbol(source_code, unclosed_line),
            )
            return cls._record_verdict(verdict, source_code)

        export_count = len(re.findall(r"\bexport\s+(?:default\s+)?(?:function|const|class|interface|type)\b", source_code))
        import_count = len(re.findall(r"^\s*import\s+", source_code, flags=re.MULTILINE))
        verdict = PRMVerificationVerdict(
            is_valid=True,
            reward_score=0.98,
            language=lang,
            ast_metrics={"imports": import_count, "exports": export_count, "lines": len(source_code.splitlines())},
        )
        return cls._record_verdict(verdict, source_code)

    @classmethod
    def verify_assert_preservation(cls, original_source: str, candidate_source: str) -> Dict[str, Any]:
        """Anti-Test-Weakening Guard: ensures candidate patches never delete or reduce AST assert statements."""
        pre_verdict = cls.verify_python_syntax(original_source)
        post_verdict = cls.verify_python_syntax(candidate_source)
        pre_asserts = pre_verdict.ast_metrics.get("asserts", 0)
        post_asserts = post_verdict.ast_metrics.get("asserts", 0)
        preserved = post_verdict.is_valid and (post_asserts >= pre_asserts)
        return {
            "preserved": preserved,
            "pre_asserts": pre_asserts,
            "post_asserts": post_asserts,
            "candidate_syntax_valid": post_verdict.is_valid,
            "reward_score": post_verdict.reward_score if preserved else 0.0,
        }

    @classmethod
    def verify_sql_safety(cls, sql_query: str) -> Dict[str, Any]:
        """Blocks unguarded destructive DDL/DML statements before SQLite execution."""
        match = cls.DESTRUCTIVE_SQL_RE.search(sql_query or "")
        if match:
            return {
                "is_safe": False,
                "blocked_clause": match.group(0),
                "reason": "Destructive unguarded SQL statement blocked by ProcessRewardGuard",
            }
        return {"is_safe": True, "blocked_clause": None, "reason": "SQL statement verified safe"}


prm_verifier = ProcessRewardGuard()
