from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_routing_head = """        # REAL HARDWARE TOGGLE
        elif intent == "HARDWARE_OS_SETTING":
            ok, spoken_text = self.hardware.execute_hardware_command(raw_text)
            execution_backend = "HARDWARE_OS_CONTROLLER\""""

new_routing_head = """        # INSTANT GREETING REFLEX
        elif intent == "GREETING":
            spoken_text = f"Hey! {self.config.agent_name} here. What are we building today?"
            execution_backend = "LOCAL_SLOT_FILL"

        # REAL HARDWARE TOGGLE
        elif intent == "HARDWARE_OS_SETTING":
            ok, spoken_text = self.hardware.execute_hardware_command(raw_text)
            execution_backend = "HARDWARE_OS_CONTROLLER\""""

if old_routing_head in code:
    code = code.replace(old_routing_head, new_routing_head)
    target.write_text(code, encoding="utf-8")
    print("[✓] Attached GREETING reflex directly into engine_harness.py")
else:
    print("[i] Greeting check already present in engine_harness.py")
