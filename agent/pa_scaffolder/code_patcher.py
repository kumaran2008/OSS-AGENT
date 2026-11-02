import ast
import re
from pathlib import Path
from typing import Tuple, List, Optional


class ASTCodePatcher:
    """
    Production-Grade AST Code Patcher with Multi-Level Fuzzy Diff Matching.
    Tolerates line number shifts, trailing space changes, and newline differences.
    Pre- and post-validates Abstract Syntax Trees before committing changes to disk.
    """

    HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    @staticmethod
    def validate_syntax(source_code: str, filename: str = "<memory>") -> Tuple[bool, str]:
        """Validates that Python code parses into a valid Abstract Syntax Tree."""
        if not filename.endswith(".py") and filename != "<memory>":
            return True, "NON_PYTHON_FILE"
        try:
            ast.parse(source_code, filename=filename)
            return True, "SYNTAX_VALID"
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}"

    @classmethod
    def apply_fuzzy_diff(cls, original_content: str, patch_diff: str) -> str:
        """
        Applies a unified diff with 3-tier fuzzy matching to tolerate shifted line numbers
        and trailing whitespace discrepancies.
        """
        # Normalize newlines to prevent Windows CRLF / POSIX LF mismatches
        orig_norm = original_content.replace("\r\n", "\n")
        diff_norm = patch_diff.replace("\r\n", "\n")

        orig_lines = orig_norm.splitlines(keepends=True)
        diff_lines = diff_norm.splitlines(keepends=True)

        patched_lines = list(orig_lines)
        line_offset = 0
        i = 0

        while i < len(diff_lines):
            line = diff_lines[i]
            match = cls.HUNK_HEADER.match(line.strip())
            if match:
                orig_start = int(match.group(1)) - 1 + line_offset
                hunk_orig: List[str] = []
                hunk_new: List[str] = []
                i += 1

                while i < len(diff_lines) and not cls.HUNK_HEADER.match(diff_lines[i].strip()):
                    d_line = diff_lines[i]
                    if d_line.startswith("+"):
                        hunk_new.append(d_line[1:])
                    elif d_line.startswith("-"):
                        hunk_orig.append(d_line[1:])
                    elif d_line.startswith(" "):
                        hunk_orig.append(d_line[1:])
                        hunk_new.append(d_line[1:])
                    elif d_line.strip() == "":
                        # Empty context line
                        hunk_orig.append("\n")
                        hunk_new.append("\n")
                    i += 1

                orig_len = len(hunk_orig)
                best_match_idx = -1
                window = 35

                # Tier 1: Exact search in local window (+/- 35 lines)
                search_start = max(0, orig_start - window)
                search_end = min(len(patched_lines) - orig_len + 1, orig_start + window)

                for idx in range(search_start, search_end):
                    if patched_lines[idx : idx + orig_len] == hunk_orig:
                        best_match_idx = idx
                        break

                # Tier 2: Exact search across the entire file
                if best_match_idx == -1:
                    for idx in range(len(patched_lines) - orig_len + 1):
                        if patched_lines[idx : idx + orig_len] == hunk_orig:
                            best_match_idx = idx
                            break

                # Tier 3: Rstrip search (ignores trailing whitespace differences)
                if best_match_idx == -1:
                    hunk_orig_rstrip = [l.rstrip() for l in hunk_orig]
                    for idx in range(len(patched_lines) - orig_len + 1):
                        slice_rstrip = [l.rstrip() for l in patched_lines[idx : idx + orig_len]]
                        if slice_rstrip == hunk_orig_rstrip:
                            best_match_idx = idx
                            break

                if best_match_idx != -1:
                    patched_lines[best_match_idx : best_match_idx + orig_len] = hunk_new
                    line_offset += len(hunk_new) - orig_len
                else:
                    target_preview = "".join(hunk_orig[:3]).strip()
                    raise RuntimeError(
                        f"Failed to find matching context for diff hunk around line {orig_start + 1}. "
                        f"Expected snippet:\n'{target_preview}'"
                    )
            else:
                i += 1

        return "".join(patched_lines)

    @classmethod
    def patch_file(cls, file_path: str, diff_text: str) -> Tuple[bool, str]:
        """
        Reads, checks syntax, applies fuzzy patch, verifies AST syntax, and commits atomically.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return False, f"Target file does not exist: {file_path}"

        original_content = path.read_text(encoding="utf-8")

        # 1. Pre-patch syntax validation
        if path.suffix == ".py":
            valid, err = cls.validate_syntax(original_content, str(path))
            if not valid:
                return False, f"Original file already has syntax error: {err}"

        # 2. Apply Fuzzy Diff
        try:
            patched_content = cls.apply_fuzzy_diff(original_content, diff_text)
        except Exception as e:
            return False, f"Patch application failed: {str(e)}"

        # 3. Post-patch AST validation
        if path.suffix == ".py":
            valid, err = cls.validate_syntax(patched_content, str(path))
            if not valid:
                return False, f"Patch rejected! Changes introduce syntax corruption: {err}"

        # 4. Atomic commit to disk
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            path.rename(backup_path)
            path.write_text(patched_content, encoding="utf-8")
            if backup_path.exists():
                backup_path.unlink()
            return True, f"Successfully patched {path.name} with syntax verified."
        except Exception as e:
            if backup_path.exists():
                backup_path.rename(path)
            return False, f"Failed writing patched file: {str(e)}"
