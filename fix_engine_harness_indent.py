from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# Correct replacement method with exact 4-space class indentation
proper_method = """    async def dispatch_tool_with_self_healing(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        patch_synthesizer: Optional[Callable[[str, str, str], str]] = None
    ) -> Dict[str, Any]:
        \"\"\"
        Dispatches tool via Process-Isolated Self-Healer:
        Runs in a child process with pre-flight AST syntax & canary validation.
        \"\"\"
        self.isolated_healer.workspace_root = self.tools.workspace_root

        def _fallback_synthesizer(path_str: str, code_str: str, err: str) -> str:
            if patch_synthesizer:
                return patch_synthesizer(path_str, code_str, err)
            return code_str

        res = await self.isolated_healer.dispatch_with_preflight_healing(
            tool_name=tool_name,
            tool_args=tool_args,
            patch_synthesizer=_fallback_synthesizer
        )

        return {
            "success": res.success,
            "output": res.output,
            "repaired": res.repaired,
            "attempts": res.attempts,
            "latency_sec": res.latency_sec,
            "pre_flight_passed": res.pre_flight_passed,
            "error": res.error,
            "explanation": res.diagnostics
        }
"""

# Replace whichever unindented or broken variant exists
code = re.sub(
    r'^[ \t]*async def dispatch_tool_with_self_healing\([^)]+\) -> Dict\[str, Any\]:.*?(?=\n    def _default_llm_patch_synthesizer|\n    async def|\n    def )',
    proper_method.rstrip(),
    code,
    flags=re.DOTALL | re.MULTILINE
)

target.write_text(code, encoding="utf-8")

# Verify syntax compiles without IndentationError
import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] engine_harness.py compiled successfully with clean 4-space indentation.")
