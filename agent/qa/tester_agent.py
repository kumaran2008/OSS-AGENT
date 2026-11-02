import re
from pathlib import Path
from typing import List, Optional
from llm.router import ModelRouter, AllModelsFailedError
from llm.validators import is_non_empty_code_block
from llm.prompts import SYSTEM_DEBUG_PROMPT
from tools.filesystem import SafeFileSystem
from agent.masons import extract_code_block
from tools.dashboard import dashboard
from agent.training import experience_buffer


class TesterAgent:
    """
    Tester / QA Engineer Agent with automated telemetry and experience capture.
    Specializes in test execution diagnostics, stack-trace breakdown,
    regression isolation, and automated root-cause repair.
    """

    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        self.router = router
        self.fs = fs

    def _extract_relevant_errors(self, file_path: str, raw_output: str, max_lines: int = 40) -> str:
        fname = Path(file_path).name
        lines = raw_output.splitlines()
        matched = []

        for i, line in enumerate(lines):
            if fname in line or any(k in line.lower() for k in ["error", "fail", "traceback", "exception", "syntaxerror"]):
                start = max(0, i - 2)
                end = min(len(lines), i + 6)
                matched.extend(lines[start:end])

        if matched:
            seen = set()
            unique_lines = [x for x in matched if not (x in seen or seen.add(x))]
            return "\n".join(unique_lines[:max_lines])

        return "\n".join(lines[-max_lines:])

    def attempt_fix(self, file_path: str, test_output: str) -> str:
        dashboard.emit("STATE_CHANGE", {"state": "WORKING"})
        dashboard.emit("LOG_STREAM", {"message": f"Tester isolating failures in {Path(file_path).name}..."})

        try:
            current_content = self.fs.read_file(file_path)
        except FileNotFoundError:
            current_content = "(file does not exist)"

        relevant_traces = self._extract_relevant_errors(file_path, test_output)

        prompt = (
            f"File targeted for repair: {file_path}\n"
            f"--- CURRENT CONTENT ---\n{current_content}\n--- END CONTENT ---\n\n"
            f"--- TEST HARNESS / COMPILER ERROR OUTPUT ---\n{relevant_traces}\n--- END ERROR ---\n\n"
            "Task: Diagnose the root cause of the error above and provide the fully corrected replacement code. "
            "Return the entire updated file content enclosed in markdown code fences (```)."
        )

        try:
            res, model_used = self.router.complete_with_fallback(
                "debug",
                [{"role": "system", "content": SYSTEM_DEBUG_PROMPT}, {"role": "user", "content": prompt}],
                validate_fn=is_non_empty_code_block,
            )
            new_content = extract_code_block(res)
            self.fs.write_file(file_path, new_content)

            # Record positive patch candidate to experience buffer
            experience_buffer.record_trajectory(
                agent_role="tester",
                task_type="repair_patch",
                input_context=prompt,
                action_output=new_content,
                outcome_reward=1.0,
                metadata={"file_path": file_path, "model_used": model_used},
            )

            print(f"[Tester/QA] {file_path} patched via {model_used}")
            dashboard.emit("LOG_STREAM", {"message": f"Tester patched {Path(file_path).name} using [{model_used}]"})
            return new_content

        except AllModelsFailedError as e:
            # Record failed resolution attempt
            experience_buffer.record_trajectory(
                agent_role="tester",
                task_type="repair_patch",
                input_context=prompt,
                action_output=str(e),
                outcome_reward=-1.0,
                metadata={"file_path": file_path, "status": "failed"},
            )

            print(f"[Tester/QA] Debug failed on all models for {file_path}: {e}")
            dashboard.emit("STATE_CHANGE", {"state": "ERROR"})
            dashboard.emit("LOG_STREAM", {"message": f"Patch resolution failed for {Path(file_path).name}"})
            return current_content

    def diagnose_and_patch(self, issue: dict, test_output: str) -> bool:
        target_file = None
        for line in test_output.splitlines():
            m = re.search(r"([a-zA-Z0-9_\-/]+\.py)", line)
            if m:
                candidate = m.group(1)
                try:
                    if self.fs.read_file(candidate):
                        target_file = candidate
                        break
                except Exception:
                    continue

        if not target_file:
            try:
                for p in Path(self.fs.workspace_root).rglob("*.py"):
                    if "test" not in p.name.lower() and not p.name.startswith("."):
                        target_file = str(p.relative_to(self.fs.workspace_root))
                        break
            except Exception:
                target_file = "main.py"

        if not target_file:
            return False

        try:
            fixed_code = self.attempt_fix(target_file, test_output)
            if fixed_code:
                self.fs.write_file(target_file, fixed_code)
                return True
        except Exception as e:
            dashboard.emit("LOG_STREAM", {"message": f"[TesterAgent] Fix attempt error: {e}"})
        return False
