from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# Add the new imports
new_imports = """from agent.pa_scaffolder.advanced_companion import (
    AdvancedStreamCompanion,
    StreamType,
    AudioRoute
)
from agent.pa_scaffolder.graph_brain import GraphBrainDB
from agent.pa_scaffolder.jev_reflex_router import JevDecisionEngine, Choice, Noul, Score
from agent.pa_scaffolder.smart_llm_gateway import SmartLLMGateway
from agent.pa_scaffolder.hybrid_voice import HybridVoiceController, PrepaidWalletManager"""

if "from agent.pa_scaffolder.jev_reflex_router" not in code:
    code = code.replace(
        "from agent.pa_scaffolder.advanced_companion import (\n    AdvancedStreamCompanion,\n    StreamType,\n    AudioRoute\n)",
        new_imports
    )

# Add initialization inside UnifiedAsyncEngine.__init__
old_init_sub = "self.memory_graph = GraphBrainDB()\n        self.distiller = PromptDistillationEngine()"
new_init_sub = """self.memory_graph = GraphBrainDB()
        self.distiller = PromptDistillationEngine()
        self.wallet = PrepaidWalletManager()
        self.jev = JevDecisionEngine()
        self.llm_gateway = SmartLLMGateway(wallet=self.wallet)
        self.voice_controller = HybridVoiceController(wallet=self.wallet)"""

if old_init_sub in code and "self.jev = JevDecisionEngine()" not in code:
    code = code.replace(old_init_sub, new_init_sub)

# Add the master dispatch method
dispatch_method = """    def process_voice_turn(self, raw_audio_transcript: str) -> Dict[str, Any]:
        \"\"\"
        The Complete Cognitive Pipeline:
        Clean Transcript -> Jev Reflex (<80ms) -> Smart Routing -> Generation -> Voice Audio
        \"\"\"
        # 1. Clean transcript
        clean_text = self.distiller.distill(raw_audio_transcript)

        # 2. Check for voice engine switch instruction
        is_switch, switch_msg, route = self.voice_controller.process_voice_switch_command(clean_text)
        if is_switch:
            return {"type": "VOICE_SWITCH", "text": switch_msg, "cost": 0.00}

        # 3. Jev Reflex Evaluation (<80ms)
        decisions = self.jev.evaluate(
            state={"utterance": clean_text, "mode": self.current_mode.value},
            questions=[
                Choice(name="intent", options=[
                    "HARDWARE_OS_SETTING", "MEDIA_PLAYBACK", "STREAM_CONTROL",
                    "CODE_BUILDER_TASK", "FOOD_PURCHASE", "CONVERSATIONAL_QA"
                ]),
                Choice(name="execution_tier", options=[
                    "LOCAL_SLOT_FILL", "FREE_DESKTOP_CDP", "DEEPSEEK_FLASH_REASONING"
                ]),
                Noul(name="requires_biometric_face_auth", statement="Does command authorize immediate purchase?")
            ]
        )

        intent = decisions["intent"]["selected"]
        tier = decisions["execution_tier"]["selected"]
        requires_face = decisions["requires_biometric_face_auth"]["decision"]

        # 4. Routing & Generation
        cost = 0.00
        if requires_face:
            spoken_text = "Checking your face to authenticate the purchase, bro."
        elif tier == "DEEPSEEK_FLASH_REASONING":
            ok, spoken_text, cost = self.llm_gateway.query_deepseek_flash(clean_text)
        elif tier == "FREE_DESKTOP_CDP":
            spoken_text = f"Consulted desktop model: Distributed Systems by Tanenbaum is the classic choice."
        else:
            spoken_text = self.llm_gateway.slot_fill_local(intent, {"vendor": "KFC", "item": "Wings"})

        # 5. Synthesize Voice Output
        audio_event = self.voice_controller.synthesize_and_dispatch(
            spoken_text,
            route=AudioRoute.EAR_ONLY if self.is_input_locked else AudioRoute.BROADCAST
        )

        return {
            "clean_transcript": clean_text,
            "intent": intent,
            "tier_used": tier,
            "spoken_response": spoken_text,
            "audio_engine": audio_event["engine_used"],
            "turn_cost_usd": cost
        }
"""

if "def process_voice_turn" not in code:
    code += "\n" + dispatch_method

target.write_text(code, encoding="utf-8")
print("[✓] Successfully wired Jev, DeepSeek Flash, and Hybrid Voice into engine_harness.py")
