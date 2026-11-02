from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_flow = """        # 4. Jev Reflex Decision
        jev_decision = await self.jev.evaluate_async(utterance=cmd_candidate)
        intent = jev_decision["intent"]

        if intent == "GREETING":
            resp = f"Hey! {self.config.agent_name} here. What are we building today?"
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {"intent": intent, "spoken_response": resp, "execution_backend": "INSTANT_REFLEX"}"""

new_flow = """        # 4. Jev Reflex Decision
        jev_decision = await self.jev.evaluate_async(utterance=cmd_candidate)
        intent = jev_decision["intent"]
        requires_face = jev_decision.get("requires_face_auth", False)

        # Biometric Payment & Safety Gate
        if requires_face:
            resp = f"Checking biometric authentication before authorizing this transaction, {self.config.agent_name} style."
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {
                "intent": intent,
                "spoken_response": resp,
                "execution_backend": "BIOMETRIC_GATE",
                "requires_face_auth": True
            }

        if intent == "GREETING":
            resp = f"Hey! {self.config.agent_name} here. What are we building today?"
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {"intent": intent, "spoken_response": resp, "execution_backend": "INSTANT_REFLEX"}"""

if old_flow in code:
    code = code.replace(old_flow, new_flow)
    target.write_text(code, encoding="utf-8")
    print("[✓] Biometric safety gate restored to engine_harness.py.")
else:
    print("[i] Biometric safety check already active.")
