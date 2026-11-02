from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Update imports
if "from agent.pa_scaffolder.rooms_engine import" not in code:
    code = "from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode, SystemTelemetryCache\n" + code

# 2. Update __init__
if "self.rooms =" not in code:
    anchor = "self.tools = ToolRegistry()"
    code = code.replace(anchor, anchor + "\n        self.rooms = RoomsEngine(workspace_root=self.tools.workspace_root)")

# 3. Intercept mode transition in process_voice_turn
transition_block = """        # -------------------------------------------------------------
        # ROOMS ENGINE TRANSITION INTERCEPTOR ("let's lock in", "builder mode")
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
"""

if "ROOMS ENGINE TRANSITION INTERCEPTOR" not in code:
    anchor = "        # -------------------------------------------------------------\n        # JEV SCREEN CODE TRIAGE INTERCEPTOR"
    if anchor in code:
        code = code.replace(anchor, transition_block + "\n" + anchor)
    else:
        # Fallback placement before Jev evaluate_async
        anchor2 = "        jev_decision = await self.jev.evaluate_async("
        code = code.replace(anchor2, transition_block + "\n" + anchor2)

target.write_text(code, encoding="utf-8")
print("[✓] Successfully wired RoomsEngine into engine_harness.py")
