import os
import json
from pathlib import Path
from agent.memory.federated_ledger import SharedRootLedger, WorkerAgentScratchpad
from agent.memory.turn_retriever import FederatedTurnRetriever
from agent.orchestrator.loop import AutonomousAgentLoop

workspace = Path("./workspace")
workspace.mkdir(exist_ok=True)

# 1. Seed Shared Root Ledger state
root = SharedRootLedger(str(workspace), task_slug="distributed-cache")
builder = WorkerAgentScratchpad(root, agent_id="builder_01", role="builder")
builder.propose_invariant("Never serialize session objects with pickle; use msgpack")
builder.sync_to_root(verified_facts=["Redis cluster benchmark passed on port 6379"])

# 2. Seed a private Worker Scratchpad (Tester has private uncommitted state)
tester = WorkerAgentScratchpad(root, agent_id="tester_01", role="tester")
tester.record_hypothesis("Memory leak detected when session payloads exceed 64KB")

# 3. Seed an archived turn history log (.jsonl)
history_dir = workspace / ".codex" / "history"
history_dir.mkdir(parents=True, exist_ok=True)
with open(history_dir / "window_1.jsonl", "w") as f:
    f.write(json.dumps({
        "timestamp": 1720000000,
        "window_id": 1,
        "tool": "pytest",
        "payload": "pytest tests/test_cache.py",
        "result_summary": "PASSED tests/test_cache.py::test_msgpack_serialization"
    }) + "\n")

# 4. Initialize Retriever and test cross-layer queries
retriever = FederatedTurnRetriever(str(workspace))

print("=== SEARCH QUERY: 'msgpack serialization' ===")
results = retriever.search("msgpack serialization", top_k=3)
for r in results:
    print(f"- [{r.source_type} | {r.section}] (Score: {r.relevance_score})\n    {r.content}")

print("\n=== SEARCH QUERY: 'memory leak session payloads' ===")
results = retriever.search("memory leak session payloads", top_k=3)
for r in results:
    print(f"- [{r.source_type} | {r.section}] (Score: {r.relevance_score})\n    {r.content}")

# 5. Test tool dispatch via the agent loop
print("\n=== IN-LOOP AGENT RETRIEVAL TOOL TEST ===")
agent = AutonomousAgentLoop(
    workspace_root=str(workspace),
    task_slug="distributed-cache",
    agent_id="reviewer_01",
    role="reviewer",
    base_instructions="Review security standards."
)

query_action = {
    "tool_call": {
        "name": "ledger_query_memory",
        "args": {"query": "pickle msgpack security"}
    }
}
print(agent.run_turn(query_action))
