import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from agent.memory.codex_store import codex_ledger


@dataclass
class PRMStepResult:
    valid: bool
    score: float
    error_message: Optional[str] = None
    suggested_repair_prompt: Optional[str] = None


class ProcessRewardGuard:
    """
    Step-Level Process Verifier (PRM). Intercepts every code block and
    tool execution in sub-100ms before context corruption or disk writes occur.
    """

    def __init__(self, auto_record_failures_to_ledger: bool = True):
        self.auto_record = auto_record_failures_to_ledger

    def verify_python_code(self, code: str, filepath: str = "snippet.py") -> PRMStepResult:
        """Validates AST correctness, syntax boundaries, and unclosed brackets."""
        if not code or not code.strip():
            return PRMStepResult(
                valid=False,
                score=-0.5,
                error_message="Empty code buffer emitted.",
                suggested_repair_prompt="The generated code was blank. Provide complete file contents.",
            )

        # 1. AST Syntax Parse (<10ms)
        try:
            tree = ast.parse(code, filename=filepath)
        except SyntaxError as e:
            error_details = f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}"
            if e.text:
                error_details += f"\nCode context: {e.text.strip()}"

            if self.auto_record:
                codex_ledger.record_failed_hypothesis(f"Syntax break in {filepath}: {error_details}")

            return PRMStepResult(
                valid=False,
                score=-0.8,
                error_message=error_details,
                suggested_repair_prompt=(
                    f"AST Parsing failed with {error_details}. "
                    f"Fix indentation, missing colons, or mismatched brackets before returning code."
                ),
            )

        # 2. Structural Sanity Checks
        num_nodes = len(list(ast.walk(tree)))
        if num_nodes < 3:
            return PRMStepResult(
                valid=False,
                score=-0.3,
                error_message="Code contains no functional statements or expressions.",
                suggested_repair_prompt="Ensure the implementation contains actual logic, not just comments.",
            )

        return PRMStepResult(valid=True, score=1.0)

    def verify_shell_execution(self, command: str, returncode: int, stderr: str, stdout: str) -> PRMStepResult:
        """Evaluates shell execution results immediately to prevent compounding terminal errors."""
        if returncode != 0:
            err_snip = stderr.strip() if stderr else stdout.strip()
            summary = f"Command '{command}' exited with code {returncode}. Error snippet: {err_snip[:250]}"

            if self.auto_record:
                codex_ledger.record_failed_hypothesis(summary)

            return PRMStepResult(
                valid=False,
                score=-0.6,
                error_message=summary,
                suggested_repair_prompt=f"Command failed with code {returncode}. Trace: {err_snip[:400]}",
            )

        return PRMStepResult(valid=True, score=0.5)


# Singleton instance ready for import across Masons and Orchestrator
prm_guard = ProcessRewardGuard()
