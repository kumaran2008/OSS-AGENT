from agent.pa_scaffolder import FloatingCompanionBridge, FaceState

companion = FloatingCompanionBridge(agent_name="Hype")

print("=== 1. IDLE STATE ===")
print(companion.render_widget_frame())

print("\n=== 2. THINKING (LLM REASONING) ===")
companion.set_state(FaceState.THINKING)
print(companion.render_widget_frame(message="Refactoring auth.py..."))

print("\n=== 3. CELEBRATING (TESTS PASSED) ===")
companion.set_state(FaceState.CELEBRATE)
print(companion.render_widget_frame(message="12/12 Tests Passing! ✨"))

print("\n=== 4. ALERT (PERMISSION REQUIRED) ===")
companion.set_state(FaceState.ALERT)
print(companion.render_widget_frame(message="Confirm destructive edit?"))

print("\n=== 5. GHOST MODE (CLICK-THROUGH) ===")
companion.set_ghost_mode(True)
assert companion.state == FaceState.GHOST
print(companion.render_widget_frame())

print("\n=== 6. SPEECH BUBBLE STREAMING TEST ===")
companion.stream_speech("Hello Operator! Hype is online with zero-lag audio ready.", chunk_delay=0.01)

print("\n>>> PHASE 2 VERIFICATION PASSED: Floating Companion Bridge is active with 0 errors.")
