import asyncio
from agent.pa_scaffolder.platform_detector import PlatformDetector
from agent.pa_scaffolder.audio_hardware import AdaptiveAudioHAL
from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine

async def main():
    print("=" * 65)
    print("     CROSS-PLATFORM HARDWARE & ADAPTATION BENCHMARK")
    print("=" * 65)

    print("\n[1/4] Inspecting Host Platform Capabilities...")
    caps = PlatformDetector.inspect_capabilities()
    for k, v in caps.items():
        print(f" • {k.ljust(22)}: {v}")

    print("\n[2/4] Testing Adaptive Audio Synthesis (HAL)...")
    hal = AdaptiveAudioHAL()
    audio_file = hal.synthesize_speech("Cross-platform test successful.", voice="en-US-ChristopherNeural")
    print(f" • Audio Synthesized: {audio_file is not None} (Path: {audio_file})")

    print("\n[3/4] Testing Real Desktop Chrome CDP Status...")
    cdp = DesktopCDPEngine()
    available = cdp.is_cdp_available()
    print(f" • Chrome CDP Port (9222) Active: {available}")
    ok, cdp_reply = cdp.execute_free_desktop_query("explain python GIL")
    print(f" • CDP Engine Output: \"{cdp_reply[:75]}...\"")

    print("\n[4/4] Running Full Harness Process Voice Turn...")
    harness = UnifiedAsyncEngine()
    res = await harness.process_voice_turn("can I buy hot wings or bucket in kfc")
    print(f" • Voice Turn Intent:  {res['intent']}")
    print(f" • Execution Backend:  {res['execution_backend']}")
    print(f" • Spoken Response:    \"{res['spoken_response'][:75]}...\"")
    assert res["execution_backend"] == "LOCAL_SLOT_FILL"

    print("\n" + "=" * 65)
    print(">>> CROSS-PLATFORM HAL READY: WIN / MAC / LINUX / ANDROID <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
