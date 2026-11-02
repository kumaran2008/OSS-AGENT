from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add IsolatedSelfHealer import
if "from agent.pa_scaffolder.isolated_self_healer import IsolatedSelfHealer" not in code:
    code = "from agent.pa_scaffolder.isolated_self_healer import IsolatedSelfHealer, IsolatedExecutionResult\n" + code

# 2. Add isolated_healer instance to UnifiedAsyncEngine.__init__
old_init = "self.self_healer = SelfRepairEngine(self.tools.workspace_root)"
new_init = old_init + "\n        self.isolated_healer = IsolatedSelfHealer(self.tools.workspace_root)"

if old_init in code and "self.isolated_healer =" not in code:
    code = code.replace(old_init, new_init)

# 3. Upgrade dispatch_tool_with_self_healing to use IsolatedSelfHealer
old_method_anchor = "    async def dispatch_tool_with_self_healing("
new_dispatch_method = """    async def dispatch_tool_with_self_healing(
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
            # Default fallback repair
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

if old_method_anchor in code:
    # Replace the existing method body cleanly
    import re
    code = re.sub(
        r'    async def dispatch_tool_with_self_healing\([^)]+\) -> Dict\[str, Any\]:.*?(?=\n    async def|\n    def|\Z)',
        new_dispatch_method.strip(),
        code,
        flags=re.DOTALL
    )

target.write_text(code, encoding="utf-8")
print("[✓] Integrated IsolatedSelfHealer into engine_harness.py.")
