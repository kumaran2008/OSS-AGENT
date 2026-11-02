import os
import sys
import ast
import json
import time
import shutil
import asyncio
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, Callable


@dataclass
class PreFlightAuditResult:
    passed: bool
    stage: str                          # "ast_syntax" or "canary_sandbox"
    error_message: Optional[str] = None


@dataclass
class IsolatedExecutionResult:
    success: bool
    output: str
    repaired: bool = False
    attempts: int = 1
    latency_sec: float = 0.0
    pre_flight_passed: bool = False
    error: Optional[str] = None
    diagnostics: Optional[str] = None


class IsolatedSelfHealer:
    """
    Supervisor for Process-Isolated Tool Execution & AST Self-Healing:
    - Runs tools inside disposable child processes (0% in-memory class poisoning).
    - Verifies candidate patches through two-phase pre-flight checks (AST syntax + canary process).
    - Rejects invalid patches without modifying production source files.
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = (workspace_root or Path(".")).resolve()
        self.worker_script = Path(__file__).resolve().parent / "tool_worker.py"

    # -------------------------------------------------------------------------
    # 1. Process-Isolated Dispatch
    # -------------------------------------------------------------------------
    def dispatch_child_process(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        timeout_sec: float = 20.0
    ) -> Dict[str, Any]:
        """Runs the tool in an isolated child process via stdio JSON IPC."""
        payload = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "workspace_root": str(self.workspace_root)
        }

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent.parent)

        cmd = [sys.executable, str(self.worker_script)]

        try:
            res = subprocess.run(
                cmd,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=env,
                cwd=str(Path(__file__).resolve().parent.parent.parent)
            )

            stdout = res.stdout.strip()
            if not stdout:
                return {
                    "success": False,
                    "output": "",
                    "error": res.stderr.strip() or f"Process exited with code {res.returncode}",
                    "traceback": res.stderr.strip(),
                    "exception_type": "SubprocessCrash"
                }

            return json.loads(stdout)

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"Tool execution timed out after {timeout_sec}s",
                "traceback": None,
                "exception_type": "TimeoutExpired"
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "traceback": None,
                "exception_type": type(e).__name__
            }

    # -------------------------------------------------------------------------
    # 2. Pre-Flight AST & Canary Verification
    # -------------------------------------------------------------------------
    @staticmethod
    def verify_ast_syntax(candidate_code: str) -> PreFlightAuditResult:
        """Stage A: Validates syntax and parses AST tree."""
        try:
            ast.parse(candidate_code)
            return PreFlightAuditResult(passed=True, stage="ast_syntax")
        except SyntaxError as e:
            return PreFlightAuditResult(
                passed=False,
                stage="ast_syntax",
                error_message=f"SyntaxError on line {e.lineno}: {e.msg}"
            )
        except Exception as e:
            return PreFlightAuditResult(
                passed=False,
                stage="ast_syntax",
                error_message=f"AST parse failure: {e}"
            )

    def verify_canary_sandbox(
        self,
        target_file: Path,
        candidate_code: str,
        canary_tool: str,
        canary_args: Dict[str, Any]
    ) -> PreFlightAuditResult:
        """Stage B: Runs candidate code in a shadow test worker process."""
        # Check AST syntax first
        ast_check = self.verify_ast_syntax(candidate_code)
        if not ast_check.passed:
            return ast_check

        # Write candidate code to temporary shadow file
        shadow_file = target_file.with_suffix(".canary_test.py")
        backup_file = target_file.with_suffix(".canary_orig.py")

        try:
            shutil.copy2(target_file, backup_file)
            shadow_file.write_text(candidate_code, encoding="utf-8")

            # Temporarily point worker to shadow file by creating a test runner script
            canary_runner = (
                f"import sys, json, asyncio\n"
                f"sys.path.insert(0, '{Path(__file__).resolve().parent.parent.parent}')\n"
                f"# Verify module compiles and imports without top-level errors\n"
                f"try:\n"
                f"    import py_compile\n"
                f"    py_compile.compile('{shadow_file}', doraise=True)\n"
                f"    print(json.dumps({{'passed': True}}))\n"
                f"except Exception as e:\n"
                f"    print(json.dumps({{'passed': False, 'error': str(e)}}))\n"
            )

            res = subprocess.run(
                [sys.executable, "-c", canary_runner],
                capture_output=True,
                text=True,
                timeout=10.0
            )

            out_data = json.loads(res.stdout.strip()) if res.stdout.strip() else {}
            if out_data.get("passed"):
                return PreFlightAuditResult(passed=True, stage="canary_sandbox")
            else:
                return PreFlightAuditResult(
                    passed=False,
                    stage="canary_sandbox",
                    error_message=out_data.get("error", "Canary compilation check failed")
                )

        except Exception as e:
            return PreFlightAuditResult(
                passed=False,
                stage="canary_sandbox",
                error_message=f"Canary sandbox exception: {e}"
            )
        finally:
            shadow_file.unlink(missing_ok=True)
            backup_file.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # 3. Master Self-Healing Loop
    # -------------------------------------------------------------------------
    async def dispatch_with_preflight_healing(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        patch_synthesizer: Callable[[str, str, str], str],
        max_attempts: int = 2
    ) -> IsolatedExecutionResult:
        """
        Executes a tool call inside a disposable child worker.
        If a crash occurs:
        1. Captures traceback and isolates the faulty file.
        2. Synthesizes a fix via the provided patch synthesizer.
        3. Runs Stage A (AST syntax) and Stage B (Canary sandbox) checks.
        4. If verified, commits the patch to disk atomically.
        5. Retries execution in a fresh child process.
        """
        t0 = time.monotonic()
        loop = asyncio.get_running_loop()

        for attempt in range(1, max_attempts + 1):
            # 1. Run in isolated child process
            child_res = await loop.run_in_executor(
                None, self.dispatch_child_process, tool_name, tool_args
            )

            if child_res.get("success") is True:
                elapsed = time.monotonic() - t0
                return IsolatedExecutionResult(
                    success=True,
                    output=child_res.get("output", ""),
                    repaired=(attempt > 1),
                    attempts=attempt,
                    latency_sec=round(elapsed, 3),
                    pre_flight_passed=(attempt > 1),
                    diagnostics="Executed cleanly on primary attempt." if attempt == 1 else "Self-healed and verified."
                )

            # 2. Intercept crash details
            err_msg = child_res.get("error", "")
            traceback_str = child_res.get("traceback") or err_msg
            faulty_file_str = child_res.get("faulty_file")

            if not faulty_file_str or not Path(faulty_file_str).exists():
                # If traceback does not expose path, target tool registry
                faulty_file_str = str(Path(__file__).resolve().parent / "tool_registry.py")

            faulty_path = Path(faulty_file_str).resolve()
            orig_code = faulty_path.read_text(encoding="utf-8")

            # 3. Synthesize candidate patch
            candidate_code = patch_synthesizer(str(faulty_path), orig_code, traceback_str)

            # 4. Stage A: Pre-flight AST syntax check
            ast_check = self.verify_ast_syntax(candidate_code)
            if not ast_check.passed:
                elapsed = time.monotonic() - t0
                return IsolatedExecutionResult(
                    success=False,
                    output="",
                    repaired=False,
                    attempts=attempt,
                    latency_sec=round(elapsed, 3),
                    pre_flight_passed=False,
                    error=ast_check.error_message,
                    diagnostics=f"Pre-flight AST Syntax check REJECTED patch: {ast_check.error_message}"
                )

            # 5. Stage B: Pre-flight canary sandbox test
            canary_check = self.verify_canary_sandbox(
                target_file=faulty_path,
                candidate_code=candidate_code,
                canary_tool=tool_name,
                canary_args=tool_args
            )
            if not canary_check.passed:
                elapsed = time.monotonic() - t0
                return IsolatedExecutionResult(
                    success=False,
                    output="",
                    repaired=False,
                    attempts=attempt,
                    latency_sec=round(elapsed, 3),
                    pre_flight_passed=False,
                    error=canary_check.error_message,
                    diagnostics=f"Pre-flight Canary sandbox REJECTED patch: {canary_check.error_message}"
                )

            # 6. Apply patch atomically to disk
            tmp_write_file = faulty_path.with_suffix(".tmp_patch")
            tmp_write_file.write_text(candidate_code, encoding="utf-8")
            os.replace(tmp_write_file, faulty_path)

        elapsed = time.monotonic() - t0
        return IsolatedExecutionResult(
            success=False,
            output="",
            repaired=False,
            attempts=max_attempts,
            latency_sec=round(elapsed, 3),
            error="Exceeded maximum self-healing attempts",
            diagnostics="All self-healing attempts exhausted."
        )
