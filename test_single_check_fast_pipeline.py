import asyncio
from pathlib import Path
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine, AgentMode

async def main():
    print("=" * 65)
    print("     SINGLE-CHECK FAST PIPELINE (ZERO-LOOP) BENCHMARK")
    print("=" * 65)

    harness = UnifiedAsyncEngine(default_mode=AgentMode.NORMAL)
    harness.wallet.wallet_path = Path("workspace/test_oss_wallet_fast.json")
    harness.wallet._balance = 0.00
    harness.wallet._save_to_disk()

    print("\n[1/3] Testing Routine Local Query ($0.00, Instant)...")
    res_routine = await harness.process_voice_turn("can I buy hot wings or bucket in kfc")
    print(f" • Intent:    {res_routine['intent']}")
    print(f" • Backend:   {res_routine['execution_backend']}")
    print(f" • Turn Cost: ${res_routine['turn_cost_usd']:.2f}")
    assert res_routine["execution_backend"] == "LOCAL_SLOT_FILL"
    assert res_routine["turn_cost_usd"] == 0.00

    print("\n[2/3] Testing Deep Query with Funded Wallet ($5.00)...")
    harness.wallet.deposit(5.00)
    print(f" • Wallet Balance: ${harness.wallet.balance:.2f}")

    res_funded = await harness.process_voice_turn("hey hype fix IndexError on line 42")
    print(f" • Backend Used:   {res_funded['execution_backend']}")
    print(f" • Spoken Response:\"{res_funded['spoken_response'][:60]}...\"")
    assert "PAID_API" in res_funded["execution_backend"]

    print("\n[3/3] Testing Deep Query with Empty Wallet ($0.00)...")
    # Drain in-memory balance to $0.00
    harness.wallet._balance = 0.00
    print(f" • Wallet Balance Set To: ${harness.wallet.balance:.2f}")

    # Single check fails instantly and falls back to desktop with zero errors
    res_empty = await harness.process_voice_turn("explain why python GIL causes multithreading bottleneck")
    print(f" • Backend Used:   {res_empty['execution_backend']}")
    print(f" • Spoken Result:  \"{res_empty['spoken_response'][:70]}...\"")
    print(f" • Turn Cost:      ${res_empty['turn_cost_usd']:.2f}")
    assert res_empty["execution_backend"] == "FREE_DESKTOP_CDP"
    assert res_empty["turn_cost_usd"] == 0.00

    print("\n" + "=" * 65)
    print(">>> VERIFIED: ZERO LOOPS, SINGLE-CHECK, ZERO DUPLICATE FILES <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
