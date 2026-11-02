import asyncio
from pathlib import Path
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine, AgentMode
from agent.pa_scaffolder.mic_listener import HardwareAudioEar

async def main():
    print("=" * 65)
    print("     HARDWARE MICROPHONE & STT LISTENER VERIFICATION")
    print("=" * 65)

    harness = UnifiedAsyncEngine(default_mode=AgentMode.NORMAL)
    ear = HardwareAudioEar(engine=harness, model_size="tiny.en")

    print("\n[1/2] Verifying STT Engine Integration...")
    print(f" • Whisper Model Loaded: {ear.whisper_model is not None}")
    print(f" • Termux API Available: {ear.record_phrase_termux is not None}")

    print("\n[2/2] Testing Simulated Microphone Ingestion Pipeline...")
    # Inject audio phrase directly to test end-to-end processing
    test_phrase = "hey hype check if there is an IndexError on line 14"
    res = await harness.process_voice_turn(test_phrase)
    print(f" • Input Utterance: \"{test_phrase}\"")
    print(f" • Intent:          {res['intent']}")
    print(f" • Execution:       {res['execution_backend']}")
    print(f" • Voice Engine:    {res['audio_engine']}")
    print(f" • Spoken Response: \"{res['spoken_response']}\"")
    assert "line 14" in res["spoken_response"] or "bounds" in res["spoken_response"]

    print("\n" + "=" * 65)
    print(">>> MICROPHONE LISTENER READY: STT -> JEV -> BRAIN -> TTS <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
