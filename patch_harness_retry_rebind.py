from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_dispatch_method_start = "    async def dispatch_tool_with_self_healing("
end_dispatch_marker = "    def _default_llm_patch_synthesizer("

new_dispatch_method = """    async def dispatch_tool_with_self_healing(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        patch_synthesizer: Optional[Callable] = None
    ) -> Dict[str, Any]:
        \"\"\"
        Executes a tool with automatic Tester Self-Healing:
        Captures tool failures, patches source code, hot-reloads the module, and completes the task.
        \"\"\"
        try:
            result = await self.tools.dispatch(tool_name, tool_args)
            if result.success:
                return {"success": True, "output": result.output, "repaired": False}

            # Check if original exception was preserved
            orig_exc = getattr(result, "exception", None) or getattr(self.tools, "last_exception", None)
            if orig_exc is not None:
                raise orig_exc
            if result.error and any(err in result.error for err in ["IndexError", "AttributeError", "KeyError", "TypeError", "ZeroDivisionError"]):
                raise RuntimeError(result.error)
            return {"success": False, "output": result.output, "error": result.error, "repaired": False}

        except Exception as crash_exc:
            default_synthesizer = patch_synthesizer or self._default_llm_patch_synthesizer

            # Re-bind dispatcher with reloaded ToolRegistry
            async def _retry_dispatcher(t_name, t_args):
                reg_mod = sys.modules.get("agent.pa_scaffolder.tool_registry")
                if reg_mod and hasattr(reg_mod, "ToolRegistry"):
                    self.tools = reg_mod.ToolRegistry(workspace_root=self.tools.workspace_root)
                return await self.tools.dispatch(t_name, t_args)

            repair_res = await self.self_healer.attempt_self_heal_and_resume(
                original_tool_name=tool_name,
                original_tool_args=tool_args,
                crash_exception=crash_exc,
                llm_patch_synthesizer=default_synthesizer,
                tool_dispatcher_fn=_retry_dispatcher,
                pty_session=self.tools.pty,
                user_persona="engineer"
            )

            if repair_res.repaired and repair_res.task_re_executed:
                return {
                    "success": True,
                    "repaired": True,
                    "output": repair_res.task_output,
                    "explanation": repair_res.explanation
                }
            return {
                "success": False,
                "repaired": False,
                "error": str(crash_exc),
                "explanation": repair_res.explanation
            }
"""

start_idx = code.find(old_dispatch_method_start)
end_idx = code.find(end_dispatch_marker)

if start_idx != -1 and end_idx != -1:
    code = code[:start_idx] + new_dispatch_method + "\n" + code[end_idx:]
    target.write_text(code, encoding="utf-8")
    print("[✓] Updated dispatch_tool_with_self_healing in engine_harness.py.")
