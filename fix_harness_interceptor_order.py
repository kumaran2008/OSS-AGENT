from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# Remove any existing interceptor blocks to prevent duplicates
code = re.sub(r'[ \t]*# -+\n[ \t]*# (?:ROOMS ENGINE TRANSITION|TESTER MODE CONVERSATIONAL|BUILDER MODE CONVERSATIONAL)[^\n]*\n(?:[ \t]*[^\n]+\n)*?(?=[ \t]*# -+|\n[ \t]*\n[ \t]*#|\Z)', '', code)

# Clean interceptor block to inject at the very top of process_voice_turn_streaming
master_interceptors = """        # -------------------------------------------------------------
        # ROOMS ENGINE TRANSITION INTERCEPTOR
        # -------------------------------------------------------------
        switched, new_mode, switch_msg = self.rooms.evaluate_transition(raw_text)
        if switched:
            self.current_mode = new_mode
            if hasattr(self, "react_planner") and self.react_planner:
                self.react_planner.max_iterations = self.rooms.REGISTRY[new_mode].react_max_steps
            await self.voice_controller.synthesize_and_dispatch_async(switch_msg, is_system_command=True)
            return {
                "type": "MODE_SWITCH",
                "active_mode": new_mode.value,
                "spoken_response": switch_msg,
                "execution_backend": "ROOMS_ENGINE"
            }

        # -------------------------------------------------------------
        # TESTER MODE CONVERSATIONAL TASK INTERCEPTOR
        # -------------------------------------------------------------
        if self.rooms.current_mode == AgentMode.TESTER:
            test_keywords = ["test", "audit", "run", "check", "regression", "flaky", "verify"]
            if any(k in raw_text.lower() for k in test_keywords):
                return await self.handle_conversational_tester_task(raw_text)

        # -------------------------------------------------------------
        # BUILDER MODE CONVERSATIONAL TASK INTERCEPTOR
        # -------------------------------------------------------------
        if self.rooms.current_mode == AgentMode.BUILDER:
            task_keywords = ["fix", "resolve", "patch", "crash", "error", "build", "create", "implement", "app", "service"]
            if any(k in raw_text.lower() for k in task_keywords):
                return await self.handle_conversational_builder_task(raw_text)
"""

method_anchor = "    async def process_voice_turn_streaming(self, raw_audio_transcript: str) -> Dict[str, Any]:\n        raw_text = raw_audio_transcript.strip()\n"
if method_anchor in code:
    code = code.replace(method_anchor, method_anchor + master_interceptors + "\n")
else:
    # Alternative anchor
    alt_anchor = "    async def process_voice_turn_streaming(self, raw_audio_transcript: str) -> Dict[str, Any]:\n"
    code = code.replace(alt_anchor, alt_anchor + "        raw_text = raw_audio_transcript.strip()\n" + master_interceptors + "\n")

target.write_text(code, encoding="utf-8")
print("[✓] Placed Room Mode Interceptors at the top of process_voice_turn_streaming.")
