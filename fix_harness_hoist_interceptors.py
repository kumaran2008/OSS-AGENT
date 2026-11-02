from pathlib import Path
import re

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Replace any occurrences of self.tools.sandbox with self.tools.pty
code = code.replace("self.tools.sandbox.", "self.tools.pty.")

# 2. Clean out old interceptor copies to avoid duplication
code = re.sub(
    r'[ \t]*# -+\n[ \t]*# (?:ROOMS ENGINE TRANSITION|TESTER MODE CONVERSATIONAL|BUILDER MODE CONVERSATIONAL)[^\n]*\n(?:[ \t]*[^\n]+\n)*?(?=[ \t]*# -+|\n[ \t]*\n[ \t]*#|\Z)',
    '',
    code
)

# 3. Master interceptor block
interceptors_code = """        # -------------------------------------------------------------
        # ROOMS ENGINE MASTER INTERCEPTORS (Transition & Mode Tasks)
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

        if self.rooms.current_mode == AgentMode.TESTER:
            test_keywords = ["test", "audit", "run", "check", "regression", "flaky", "verify"]
            if any(k in raw_text.lower() for k in test_keywords):
                return await self.handle_conversational_tester_task(raw_text)

        if self.rooms.current_mode == AgentMode.BUILDER:
            task_keywords = ["fix", "resolve", "patch", "crash", "error", "build", "create", "implement", "app", "service"]
            if any(k in raw_text.lower() for k in task_keywords):
                return await self.handle_conversational_builder_task(raw_text)
"""

# 4. Inject right at the beginning of process_voice_turn_streaming
pattern = r'(async def process_voice_turn_streaming\([^\)]*\)[^:]*:\s*\n(?:[ \t]*"""[^\"]*"""\s*\n)?(?:[ \t]*raw_text\s*=\s*raw_audio_transcript\.strip\(\)\s*\n)?)'
match = re.search(pattern, code)

if match:
    code = code[:match.end()] + "        raw_text = raw_audio_transcript.strip()\n" + interceptors_code + "\n" + code[match.end():]
    target.write_text(code, encoding="utf-8")
    print("[✓] Successfully hoisted Room Interceptors to the top of process_voice_turn_streaming.")
else:
    print("[!] Could not match process_voice_turn_streaming signature; checking fallback.")
