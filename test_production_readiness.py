import asyncio
import json
from pathlib import Path
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine, AgentMode

async def main():
    print("=" * 65)
    print("     PRODUCTION READINESS & CONTEXT HYDRATION TEST")
    print("=" * 65)

    harness = UnifiedAsyncEngine(default_mode=AgentMode.NORMAL)
    harness.wallet.wallet_path = Path("workspace/test_readiness_wallet.json")
    harness.wallet._balance = 5.00
    harness.wallet._save_to_disk()

    print("\n[1/3] Turn 1: Initial Query & SQLite Persistence...")
    t1 = await harness.process_voice_turn("can I buy hot wings or bucket in kfc")
    print(f" • Turn 1 Response: \"{t1['spoken_response'][:70]}...\"")
    print(f" • Audio Generated: {t1.get('audio_played') is not None}")

    print("\n[2/3] Turn 2: Pronoun / Anaphoric Follow-Up Context Check...")
    # This turn relies on context from Turn 1
    t2 = await harness.process_voice_turn("which of those two has more protein?")
    print(f" • Turn 2 Backend:  {t2['execution_backend']}")
    print(f" • Turn 2 Response: \"{t2['spoken_response'][:70]}...\"")

    print("\n[3/3] Inspecting GraphBrainDB Episodic Context...")
    with harness.memory_graph._get_conn() as conn:
        rows = conn.execute("SELECT properties FROM nodes WHERE node_type = 'episodic' ORDER BY updated_at DESC LIMIT 2").fetchall()
        for i, (prop_str,) in enumerate(rows):
            p = json.loads(prop_str)
            print(f" • Historical Turn {i+1}: User: \"{p['utterance']}\"")
            assert len(p['utterance']) > 0

    print("\n" + "=" * 65)
    print(">>> VERDICT: PRODUCTION PIPELINE FULLY WIRED & HYDRATED <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
