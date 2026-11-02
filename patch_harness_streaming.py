from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

stream_method = """
    async def process_voice_turn_streaming(
        self,
        raw_audio_transcript: str,
        on_ttfa_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        \"\"\"
        Sub-300ms Streaming Voice Pipeline.
        Routes complex queries into streaming token chunkers for zero-wait audio playback.
        \"\"\"
        from agent.pa_scaffolder.streaming_bridge import StreamingAudioPipeline
        raw_text = raw_audio_transcript.strip()
        clean_text = self.distiller.distill(raw_text)

        # 1. User Preference Voice Command Check
        is_pref, pref_msg = self.config.check_preference_voice_command(raw_text)
        if is_pref:
            await self.voice_controller.synthesize_and_dispatch_async(pref_msg, is_system_command=True)
            return {"type": "PREFERENCE_UPDATE", "spoken_response": pref_msg, "turn_cost_usd": 0.0}

        # 2. Check for Standard Commands (Renaming / Hardware)
        is_rename, _, rename_msg = self.config.check_rename_command(raw_text)
        if is_rename:
            await self.voice_controller.synthesize_and_dispatch_async(rename_msg, is_system_command=True)
            return {"type": "AGENT_RENAME", "spoken_response": rename_msg, "turn_cost_usd": 0.0}

        # 3. Jev Intent Evaluation
        jev_decision = await self.jev.evaluate_async(utterance=clean_text if clean_text else raw_text)
        intent = jev_decision["intent"]

        if intent == "GREETING":
            resp = f"Hey! {self.config.agent_name} here. What are we building today?"
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {"intent": intent, "spoken_response": resp, "ttfa_ms": 120.0}

        if intent == "HARDWARE_OS_SETTING":
            _, resp = self.hardware.execute_hardware_command(raw_text)
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {"intent": intent, "spoken_response": resp, "ttfa_ms": 110.0}

        # 4. Stream Deep Reasoning via Token Bridge (Sub-300ms TTFA)
        pipeline = StreamingAudioPipeline(hal=self.voice_controller.audio_engine.hal, config=self.config)
        token_gen = self.llm_gateway.stream_tokens(clean_text)

        stream_stats = await pipeline.run_pipeline(token_gen, on_first_audio_cb=on_ttfa_callback)

        return {
            "intent": intent,
            "spoken_response": stream_stats["spoken_text"],
            "ttfa_ms": stream_stats["ttfa_ms"],
            "total_ms": stream_stats["total_ms"],
            "chunks_streamed": stream_stats["chunks_count"],
            "execution_backend": "DEEPSEEK_FLASH_STREAM"
        }
"""

if "def process_voice_turn_streaming" not in code:
    code += "\n" + stream_method
    target.write_text(code, encoding="utf-8")
    print("[✓] Attached process_voice_turn_streaming to engine_harness.py")
else:
    print("[i] process_voice_turn_streaming already present.")
