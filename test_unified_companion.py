import asyncio
import time
from pathlib import Path
from agent.core.unified_companion import (
    UnifiedAsyncEngine,
    AgentMode,
    AudioChannel,
    PromptDistillationEngine
)

async def mock_background_search():
    # Simulates searching for restaurants in the background while streaming
    await asyncio.sleep(0.3)
    return ["A2B Restaurant (0.8 km)", "Anjappar Chettinad (1.2 km)"]

async def main():
    print("=" * 65)
    print("     UNIFIED PERSONAL AGENT HARNESS BENCHMARK")
    print("=" * 65)

    engine = UnifiedAsyncEngine(default_mode=AgentMode.STREAMER)

    print("\n[1/5] Verifying Streamer/Gamer Zero-Focus Safety Guard...")
    print(f" • Active Mode: {engine.current_mode.value.upper()}")
    print(f" • Input Focus Lock Active: {engine.is_input_locked}")
    assert engine.is_input_locked is True, "Security validation failed: Focus lock must be active."

    print("\n[2/5] Testing Speech-to-Prompt Distillation...")
    raw_speech = "bro like can you ask chatgpt what is the command to dump obs replay buffer bro"
    distilled = PromptDistillationEngine.distill(raw_speech)
    print(f" • Raw:       \"{raw_speech}\"")
    print(f" • Distilled: \"{distilled}\"")
    assert "bro" not in distilled.lower()

    print("\n[3/5] Testing Dual-Channel Audio Routing...")
    # Private backstage message for the streamer's headset
    whisper_evt = engine.audio_router.route_audio(
        "Bitrate dropped by 12%. Replay saved.",
        AudioChannel.WHISPER_EAR
    )
    # Public voice response for the stream
    stream_evt = engine.audio_router.route_audio(
        "Let's go chat! Big play coming up.",
        AudioChannel.BROADCAST_STREAM
    )
    print(f" • Ear Route (Headset):  [{whisper_evt['privacy']}] \"{whisper_evt['message']}\"")
    print(f" • Stream Route (OBS):    [{stream_evt['privacy']}] \"{stream_evt['message']}\"")

    print("\n[4/5] Running 3 Parallel Stream Tasks (Clip + Timeout + Maps Search)...")
    t0 = time.perf_counter()

    parallel_tasks = {
        "obs_clip": engine.obs.save_replay_buffer(),
        "chat_ban": engine.stream_manager.timeout_user("spammer_bot_1", duration_sec=300),
        "bg_search": mock_background_search()
    }

    results = await engine.run_parallel_jobs(parallel_tasks)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f" • Completed all 3 operations in: {elapsed_ms:.2f} ms")
    print(f"   ├─ OBS Replay Sliced:  {results['obs_clip']['data']}")
    print(f"   ├─ Moderation Action:  {results['chat_ban']['data']}")
    print(f"   └─ Background Search:  {results['bg_search']['data']}")

    assert results["obs_clip"]["success"] is True
    assert results["chat_ban"]["success"] is True
    assert results["bg_search"]["success"] is True
    assert elapsed_ms < 1500, "Parallel execution delayed; check task loop concurrency."

    print("\n[5/5] Generating Editor Highlight Marker File (EDL/CSV)...")
    engine.stream_manager.mark_stream_moment("Insane 1v3 Clutch Round")
    engine.stream_manager.mark_stream_moment("Hilarious glitch moment")
    export_path = Path("stream_highlights.csv")
    csv_file = engine.stream_manager.export_editor_edl(export_path)

    print(f" • Exported timeline markers to: {csv_file}")
    content = export_path.read_text(encoding="utf-8")
    print("   " + content.replace("\n", "\n   "))

    print("\n" + "=" * 65)
    print(">>> ALL HARNESS SUBSYSTEMS VERIFIED & FULLY OPERATIONAL <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
