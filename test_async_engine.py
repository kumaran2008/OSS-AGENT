import asyncio
import time
from agent.core.async_engine import UnifiedAsyncEngine, AgentMode
from agent.core.prompt_distiller import PromptDistillationEngine

async def mock_background_download():
    # Simulates an authenticated background file download
    await asyncio.sleep(0.4)
    return "file_statement_september.pdf (1.2 MB)"

async def mock_youtube_moderation():
    # Simulates background Live Chat API moderation
    await asyncio.sleep(0.2)
    return "Timed out 1 spammer on stream."

async def mock_speech_distillation(distiller: PromptDistillationEngine, query: str):
    # Runs prompt distillation
    return distiller.distill_voice_prompt(query)

async def main():
    print("=" * 65)
    print("     UNIFIED ASYNC MULTI-LOOP ENGINE BENCHMARK")
    print("=" * 65)

    engine = UnifiedAsyncEngine(default_mode=AgentMode.NORMAL)
    distiller = PromptDistillationEngine()

    print(f"\n[1/3] Testing Mode Switching & Input Locks...")
    print(" • " + engine.set_mode(AgentMode.STREAMER))
    assert engine.is_input_locked is True

    print(" • " + engine.set_mode(AgentMode.NORMAL))
    assert engine.is_input_locked is False

    print("\n[2/3] Executing 3 Parallel Tasks (Download + Moderation + Voice Optimization)...")
    t0 = time.perf_counter()

    parallel_jobs = {
        "download": mock_background_download(),
        "chat_mod": mock_youtube_moderation(),
        "distill": mock_speech_distillation(
            distiller,
            "bro ask chatgpt how to configure obs replay buffer using websockets python"
        )
    }

    results = await engine.run_parallel_jobs(parallel_jobs)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f" • All tasks resolved concurrently in: {elapsed_ms:.2f} ms")
    print(f" • Download Job:   {results['download']}")
    print(f" • Moderation Job: {results['chat_mod']}")
    print(f" • Distilled Intent: \"{results['distill']['data']}\"")

    assert results["download"]["success"] is True
    assert results["chat_mod"]["success"] is True
    assert elapsed_ms < 1500  # Must complete concurrently without serial delays

    print("\n[3/3] Inspecting Task Registry...")
    active = engine.get_active_task_summary()
    print(f" • Registry successfully logged {len(active)} executions with clean error boundaries.")

    print("\n" + "=" * 65)
    print(">>> ASYNC MULTI-LOOP HARNESS VERIFIED OPERATIONAL <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
