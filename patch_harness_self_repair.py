from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add SelfRepairEngine import
if "from agent.pa_scaffolder.self_repair_engine import SelfRepairEngine" not in code:
    code = "from agent.pa_scaffolder.self_repair_engine import SelfRepairEngine, SelfRepairResult\n" + code

# 2. Add self_repair_engine to UnifiedAsyncEngine.__init__
old_init = "self.tools = ToolRegistry()"
new_init = old_init + "\n        self.self_healer = SelfRepairEngine(pa_root=Path('.'))"

if old_init in code and "self.self_healer =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add execute_with_self_healing method to UnifiedAsyncEngine
self_heal_method = """    async def dispatch_tool_with_self_healing(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        patch_synthesizer: Optional[Callable] = None
    ) -> Dict[str, Any]:
        \"\"\"
        Executes a tool with automatic Tester Self-Healing trap:
        If the PA's internal tool crashes, the Tester Room activates,
        repairs the PA's source code, hot-reloads the module, and completes the task.
        \"\"\"
        try:
            result = await self.tools.dispatch(tool_name, tool_args)
            if result.success:
                return {"success": True, "output": result.output, "repaired": False}
            # If tool reported logical failure with an exception pattern
            if result.error and any(err in result.error for err in ["IndexError", "AttributeError", "KeyError", "TypeError"]):
                raise RuntimeError(result.error)
            return {"success": False, "output": result.output, "error": result.error, "repaired": False}

        except Exception as crash_exc:
            # Tool crashed! Activate TESTER SELF-HEALING SUPERVISOR
            default_synthesizer = patch_synthesizer or self._default_llm_patch_synthesizer

            # Hot-rebind dispatch adapter so reloaded module takes effect
            async def _retry_dispatcher(t_name, t_args):
                # Re-instantiate desktop / tools if relevant module reloaded
                self.tools.desktop = self.tools.desktop.__class__()
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

    def _default_llm_patch_synthesizer(self, rel_path: str, orig_code: str, error_trace: str) -> Optional[str]:
        \"\"\"Fallback rule-based synthesizer when cloud LLM is offline.\"\"\"
        # Generic boundary check fix for IndexError
        if "IndexError" in error_trace and "line_count" in orig_code:
            return orig_code.replace("selected = lines[start : start + count]", "start = max(0, min(start, len(lines))); selected = lines[start : min(len(lines), start + count)]")
        return None
"""

if "def dispatch_tool_with_self_healing" not in code:
    code = code.replace("class UnifiedAsyncEngine:", "class UnifiedAsyncEngine:\n" + self_heal_method)

target.write_text(code, encoding="utf-8")
print("[✓] Integrated Self-Healing Tool Dispatcher into engine_harness.py")
