import asyncio
from pathlib import Path
from agent.pa_scaffolder.graph_brain import GraphBrainDB, NodeType
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine

async def main():
    print("=" * 70)
    print("     SCAFFOLDER GRAPHBRAIN v2 INTEGRATION TEST")
    print("=" * 70)

    # 1. Initialize Scaffolder Memory
    test_db = Path("workspace/test_scaffolder_brain.db")
    test_db.unlink(missing_ok=True)
    for ext in ["-wal", "-shm"]:
        Path(str(test_db) + ext).unlink(missing_ok=True)

    brain = GraphBrainDB(db_path=test_db)

    print("\n[1/4] Seeding Long-Term Memory (Projects, Preferences, Past Bugs)...")
    # Project node
    brain.add_or_update_node(
        node_id="proj_01",
        node_type=NodeType.PROJECT,
        label="oss-agent",
        metadata={"repo": "oss-agent", "stack": "Python 3.13, SQLite WAL, ONNX"}
    )
    # User preference
    brain.add_or_update_node(
        node_id="pref_01",
        node_type=NodeType.PREFERENCE,
        label="CodingStyle",
        metadata={"typing": "strict slots", "formatting": "black", "persona": "sharp witty brother"}
    )
    # Technical memory from earlier session
    brain.add_or_update_node(
        node_id="bug_42",
        node_type=NodeType.EPISODIC,
        label="IndexErrorLine42",
        metadata={
            "utterance": "fix IndexError subscript on line 42",
            "response": "Checked bounds on line 42 and added length guard.",
            "file": "test_streaming.py"
        }
    )
    # Directional Graph Edge
    brain.link_entities("proj_01", "bug_42", "ENCOUNTERED_BUG")
    print(" • Memory seeded: 3 distinct entity types + directional graph edge.")

    # 2. Test Associative Hybrid Search (FTS5 + Vector RRF)
    print("\n[2/4] Testing Hybrid Associative Recall for query: 'what happened with line 42?'...")
    results = brain.get_relevant_context("what happened with line 42?", top_k=2)
    print(f" • Matched {len(results)} nodes via Hybrid RRF:")
    for r in results:
        print(f"   └─ [{r['type']}] '{r['label']}' (Score: {r['rrf_score']:.5f}) -> {r['properties']}")

    assert len(results) > 0
    assert results[0]["id"] == "bug_42"
    print(" >>> Associative Hybrid Search: Verified. <<<")

    # 3. Test Graph CTE Traversal
    print("\n[3/4] Testing 2-Hop Graph Walk from Project node...")
    walk = brain.traverse_graph("proj_01", max_depth=2)
    print(f" • Graph connections found: {len(walk)}")
    for edge in walk:
        print(f"   └─ Depth {edge['depth']}: [{edge['relation']}] -> {edge['id']} ({edge['label']})")
    assert len(walk) >= 1
    assert walk[0]["id"] == "bug_42"
    print(" >>> Graph CTE Traversal: Verified. <<<")

    # 4. End-to-End Voice Turn Integration via UnifiedAsyncEngine
    print("\n[4/4] Testing UnifiedAsyncEngine process_voice_turn with GraphBrain v2...")
    harness = UnifiedAsyncEngine()
    # Point harness to test DB
    harness.memory_graph = brain

    turn_res = await harness.process_voice_turn("tell me about the bug on line 42")
    print(f" • Spoken Response: \"{turn_res['spoken_response'][:75]}...\"")
    print(f" • Backend:         {turn_res['execution_backend']}")
    print(f" • Active Intent:   {turn_res['intent']}")

    # Verify that this new turn was automatically indexed in the graph
    with brain.driver.get_connection() as conn:
        turn_count = conn.execute("SELECT COUNT(*) FROM memory_nodes WHERE entity_type = 'episodic'").fetchone()[0]
    print(f" • Total Episodic Turns Indexed in DB: {turn_count}")
    assert turn_count >= 2

    # Cleanup
    test_db.unlink(missing_ok=True)
    for ext in ["-wal", "-shm"]:
        Path(str(test_db) + ext).unlink(missing_ok=True)

    print("\n" + "=" * 70)
    print(">>> PILLAR 1: GRAPHBRAIN v2 INTEGRATED INTO SCAFFOLDER SUCCESSFULLY <<<")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
