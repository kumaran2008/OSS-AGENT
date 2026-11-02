import asyncio
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine, AgentMode

async def mock_search():
    await asyncio.sleep(0.1)
    return "Found 3 nearby cafes"

async def main():
    print("=" * 65)
    print("     PA SCAFFOLDER: COMPLETE ENGINE HARNESS VERIFICATION")
    print("=" * 65)

    engine = UnifiedAsyncEngine(default_mode=AgentMode.STREAMER_GAMING)

    print("\n[1/4] Checking Mode & Input Lock Enforcement...")
    print(f" • Mode: {engine.current_mode.value}")
    print(f" • Zero-Focus Lock Active: {engine.is_input_locked}")
    assert engine.is_input_locked is True

    print("\n[2/4] Testing Speech Distillation in Scaffolder...")
    raw = "bro like ask chatgpt how to link graph memory in python bro"
    distilled = engine.distiller.distill(raw)
    print(f" • Distilled: \"{distilled}\"")
    assert "bro" not in distilled.lower()

    print("\n[3/4] Testing Parallel Jobs with OBS & Background Tasks...")
    jobs = {
        "obs_save": engine.stream_companion.obs.save_replay_buffer(),
        "search": mock_search()
    }
    results = await engine.run_parallel_jobs(jobs)
    print(f" • OBS Buffer Result: {results['obs_save']['data']}")
    print(f" • Search Result:     {results['search']['data']}")
    assert results["obs_save"]["success"] is True
    assert results["search"]["success"] is True

    print("\n[4/4] Verifying Spatio-Temporal Graph Ingestion...")
    node = engine.memory_graph.add_or_update_node("TASK", "Scaffolder_Consolidation", {"status": "success"})
    print(f" • Memory Node Created: {node}")
    assert node.startswith("node_")

    print("\n" + "=" * 65)
    print(">>> PA SCAFFOLDER HARNESS VERIFIED 100% OPERATIONAL <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
