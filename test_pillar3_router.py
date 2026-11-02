import time
import asyncio
from agent.pa_scaffolder.complexity_gate import LatentComplexityGate, RouteDecision
from agent.pa_scaffolder.cdp_bridge import ResilientCDPBridge
from agent.pa_scaffolder.failover_controller import MultiModelFailoverController
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


async def test_pillar3():
    print("=" * 70)
    print("     PILLAR 3 VERIFICATION: ROUTER & MULTI-MODEL BRIDGE")
    print("=" * 70)

    gate = LatentComplexityGate()

    # -------------------------------------------------------------------------
    # 1. Verify Sub-15ms Radix-Tree Tier 0 Micro-Reflexes
    # -------------------------------------------------------------------------
    print("\n[1/3] Benchmarking Radix-Tree Micro-Reflex Latency (Target: <15ms)...")
    tier0_phrases = ["stop", "cancel", "shut up", "status", "who are you", "clear screen"]

    t0 = time.perf_counter()
    iterations = 500
    for i in range(iterations):
        phrase = tier0_phrases[i % len(tier0_phrases)]
        decision = gate.route(phrase)
        assert decision.tier == 0
        assert decision.action_tag is not None

    total_time_ms = (time.perf_counter() - t0) * 1000.0
    avg_latency_ms = total_time_ms / iterations
    print(f" • Executed {iterations} Trie Lookups in: {total_time_ms:.2f} ms")
    print(f" • Average Decision Latency:         {avg_latency_ms:.4f} ms")
    assert avg_latency_ms < 15.0, f"Micro-reflex latency ({avg_latency_ms:.3f}ms) exceeded 15ms target!"
    print(" >>> CRITERION 1 PASSED: Sub-15ms Tier 0 Micro-Reflexes verified. <<<")

    # -------------------------------------------------------------------------
    # 2. Verify Complexity Scoring & Routing Matrix
    # -------------------------------------------------------------------------
    print("\n[2/3] Testing Structural Complexity Scorer & Routing Matrix...")
    # Low complexity (Tier 1 SLM)
    d_low = gate.route("good morning how are you doing today")
    print(f" • Casual Greeting:     Tier {d_low.tier} ({d_low.engine_name}) | Complexity: {d_low.complexity_score:.2f}")
    assert d_low.tier == 1

    # High complexity (Tier 2 Frontier Reasoning)
    d_high = gate.route("refactor async pipeline def and optimize indexerror with git patch", budget_available=True)
    print(f" • Code / AST Task:     Tier {d_high.tier} ({d_high.engine_name}) | Complexity: {d_high.complexity_score:.2f}")
    assert d_high.tier == 2

    # High complexity without budget (Tier 3 Desktop CDP)
    d_unfunded = gate.route("refactor async pipeline def and optimize indexerror", budget_available=False)
    print(f" • Unfunded Code Task:  Tier {d_unfunded.tier} ({d_unfunded.engine_name}) | Complexity: {d_unfunded.complexity_score:.2f}")
    assert d_unfunded.tier == 3
    print(" • Routing Matrix & Complexity Scorer: 100% Verified.")

    # -------------------------------------------------------------------------
    # 3. Verify Live Failover Cascade (HTTP 429 Simulation)
    # -------------------------------------------------------------------------
    print("\n[3/3] Testing Live Failover Controller on Simulated HTTP 429...")
    failover = MultiModelFailoverController()

    chunks_collected = []
    engines_logged = set()

    # Simulate query on Tier 2 where HTTP 429 occurs
    async for token, engine_tag in failover.execute_resilient_stream(
        prompt="explain python GIL bottleneck",
        initial_tier=2,
        force_failover_429=True  # Force HTTP 429 rate-limit trigger
    ):
        chunks_collected.append(token)
        engines_logged.add(engine_tag)

    full_output = "".join(chunks_collected)
    print(f" • Engine Hops Logged: {engines_logged}")
    print(f" • Failover Message:   \"{full_output.splitlines()[1] if len(full_output.splitlines()) > 1 else full_output[:60]}\"")

    assert "FAILOVER_EVENT" in engines_logged, "Failover event was not recorded."
    assert "TIER_3_CDP" in engines_logged, "Did not cascade to Tier 3 Desktop CDP."
    print(" >>> CRITERION 2 PASSED: Automatic mid-turn failover verified. <<<")

    # -------------------------------------------------------------------------
    # 4. End-to-End Voice Harness Tier 0 Intercept
    # -------------------------------------------------------------------------
    print("\n • Testing Harness End-to-End Voice Intercept for 'status'...")
    harness = UnifiedAsyncEngine()
    turn_res = await harness.process_voice_turn("status")
    print(f"   └─ Response: \"{turn_res['spoken_response']}\"")
    print(f"   └─ Backend:  {turn_res['execution_backend']}")
    assert turn_res["execution_backend"] == "TIER_0_MICRO_REFLEX"

    print("\n" + "=" * 70)
    print(">>> PILLAR 3: ROUTER & MULTI-MODEL BRIDGE FULLY OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_pillar3())
