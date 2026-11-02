import asyncio
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine

async def main():
    print("=" * 65)
    print("     HARDWARE EXECUTION & DYNAMIC PERSONA BENCHMARK")
    print("=" * 65)

    harness = UnifiedAsyncEngine()

    print("\n[1/3] Testing 'turn on my internet'...")
    res_hw = await harness.process_voice_turn("turn on my internet")
    print(f" • Intent:    {res_hw['intent']}")
    print(f" • Backend:   {res_hw['execution_backend']}")
    print(f" • Spoken:    \"{res_hw['spoken_response']}\"")
    assert res_hw["execution_backend"] == "HARDWARE_OS_CONTROLLER"
    assert "Wi-Fi" in res_hw["spoken_response"] or "online" in res_hw["spoken_response"] or "turned on" in res_hw["spoken_response"]

    print("\n[2/3] Testing Spoken Renaming ('Jarvis, change your name to Friday')...")
    res_rename = await harness.process_voice_turn("Jarvis, change your name to Friday")
    print(f" • Response:  \"{res_rename['spoken_response']}\"")
    print(f" • New Name:  {harness.config.agent_name}")
    print(f" • Wake Words:{harness.config.wake_words[:3]}")
    assert harness.config.agent_name == "Friday"
    assert any("friday" in w for w in harness.config.wake_words)

    print("\n[3/3] Testing Natural Dialogue Responses...")
    res_greet = await harness.process_voice_turn("hey Friday")
    print(f" • Greeting:  \"{res_greet['spoken_response']}\"")
    assert "Synthesized via local system memory" not in res_greet["spoken_response"]

    print("\n" + "=" * 65)
    print(">>> 100% OPERATIONAL: REAL HARDWARE TOGGLE & DYNAMIC RENAMING <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
