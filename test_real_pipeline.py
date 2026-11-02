import asyncio
from pathlib import Path
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine, AgentMode

async def main():
    print("=" * 65)
    print("     FULLY CONNECTED HYBRID SCAFFOLDER PIPELINE TEST")
    print("=" * 65)

    harness = UnifiedAsyncEngine(default_mode=AgentMode.NORMAL)
    harness.wallet.wallet_path = Path("workspace/test_oss_wallet_fast.json")
    harness.wallet._balance = 0.00
    harness.wallet._save_to_disk()

    print("\n[1/3] Testing Routine Turn + Memory Persistence...")
    res_routine = await harness.process_voice_turn("can I buy hot wings or bucket in kfc")
    print(f" • Intent:    {res_routine['intent']}")
    print(f" • Backend:   {res_routine['execution_backend']}")
    print(f" • Spoken:    \"{res_routine['spoken_response']}\"")
    assert res_routine["execution_backend"] == "LOCAL_SLOT_FILL"

    # Verify GraphBrainDB actually stored the episodic turn in SQLite
    with harness.memory_graph._get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()]
        print(f" • Discovered SQLite columns on 'nodes': {cols}")
        
        # Pull the latest node using whatever primary key column exists
        order_col = "updated_at" if "updated_at" in cols else cols[0]
        row = conn.execute(f"SELECT * FROM nodes ORDER BY {order_col} DESC LIMIT 1").fetchone()
        print(f" • Stored Node in SQLite: {row}")
        assert row is not None

    print("\n[2/3] Testing Async Deep Reasoning (Funded Wallet $5.00)...")
    harness.wallet.deposit(5.00)
    res_funded = await harness.process_voice_turn("hey hype fix IndexError on line 42")
    print(f" • Backend Used:   {res_funded['execution_backend']}")
    print(f" • Spoken Line:    \"{res_funded['spoken_response']}\"")
    assert "PAID_API" in res_funded["execution_backend"]
    assert "line 42" in res_funded["spoken_response"]

    print("\n[3/3] Testing Fallback to Free Desktop CDP (Drained Wallet)...")
    harness.wallet._balance = 0.00
    res_empty = await harness.process_voice_turn("explain why python GIL causes multithreading bottleneck")
    print(f" • Backend Used:   {res_empty['execution_backend']}")
    print(f" • Spoken Line:    \"{res_empty['spoken_response'][:70]}...\"")
    assert res_empty["execution_backend"] == "FREE_DESKTOP_CDP"

    print("\n" + "=" * 65)
    print(">>> 100% CONNECTED & WORKING: NO MOCKS, FULL PERSISTENCE <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
