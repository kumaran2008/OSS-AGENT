import asyncio
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine

async def main():
    print("=" * 65)
    print("     STICKY BRAIN PREFERENCE STATE VERIFICATION")
    print("=" * 65)

    harness = UnifiedAsyncEngine()

    print("\n[1/3] Setting Initial Sticky State to Local SLM...")
    res_switch = await harness.process_voice_turn("switch to slm")
    print(f" • Switch Spoken:   \"{res_switch['spoken_response']}\"")
    print(f" • Locked State:    {harness.config.active_backend}")
    assert harness.config.active_backend == "slm_local"

    # Turn 1: Normal command (Should flow into SLM with ZERO prompting)
    print("\n • Normal Turn 1: \"I am exhausted after work\"")
    t1 = await harness.process_voice_turn("I am exhausted after work")
    print(f"   └─ Backend Used: {t1['execution_backend']}")
    print(f"   └─ Spoken:       \"{t1['spoken_response']}\"")
    assert t1["execution_backend"] == "LOCAL_SLM_KOKORO"

    print("\n[2/3] Explicit Spoken Switch: 'hey hype change voice streaming to google api'...")
    res_google_switch = await harness.process_voice_turn("hey hype change voice streaming to google api")
    print(f" • Switch Spoken:   \"{res_google_switch['spoken_response']}\"")
    print(f" • New Locked State:{harness.config.active_backend}")
    assert harness.config.active_backend == "google_live"

    # Turn 2: Next command (Automatically uses google_live; NO questions asked!)
    print("\n • Normal Turn 2: \"can you give me advice for my new app\"")
    t2 = await harness.process_voice_turn("can you give me advice for my new app")
    print(f"   └─ Backend Used: {t2['execution_backend']}")
    print(f"   └─ Spoken:       \"{t2['spoken_response']}\"")
    assert t2["active_backend"] == "google_live"

    print("\n[3/3] Explicit Spoken Switch: 'switch to deepseek'...")
    res_deep_switch = await harness.process_voice_turn("switch to deepseek")
    print(f" • Switch Spoken:   \"{res_deep_switch['spoken_response']}\"")
    assert harness.config.active_backend == "deepseek_flash"

    # Turn 3: Automatically uses deepseek
    print("\n • Normal Turn 3: \"fix IndexError on line 42\"")
    t3 = await harness.process_voice_turn("fix IndexError on line 42")
    print(f"   └─ Backend Used: {t3['execution_backend']}")
    print(f"   └─ Spoken:       \"{t3['spoken_response']}\"")
    assert t3["execution_backend"] == "DEEPSEEK_FLASH_STREAM"

    print("\n" + "=" * 65)
    print(">>> ZERO PROMPTING: STATE FLOWS SEAMLESSLY ACROSS ALL TURNS <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
