from agent.orchestrator.loop import AutonomousAgentLoop

# 1. Initialize agent with a compact 2000-token ceiling (simulating mobile/Termux constraints)
agent = AutonomousAgentLoop(
    workspace_root="./workspace",
    task_slug="auth-refactor",
    agent_id="builder-01",
    role="builder",
    base_instructions="Refactor session storage from pickle to json serialization.",
    token_ceiling=2000
)

print("=== Turn 1: Normal Operation (Record Invariant) ===")
resp1 = {
    "tool_call": {
        "name": "ledger_record_invariant",
        "args": {
            "invariant": "Never use pickle in session handler",
            "rationale": "Arbitrary code execution risk"
        }
    }
}
print(agent.run_turn(resp1))
print(f"Active tokens in memory: {agent.count_active_tokens()}")

# Simulate accumulating lots of code & tool context in history
agent.messages.append({
    "role": "tool",
    "content": "A" * 7000  # ~1750 tokens, pushes usage near the 2000 limit
})
print(f"\nContext after large diff injection: {agent.count_active_tokens()} tokens")

print("\n=== Turn 2: Context Full -> Model Invokes ledger_turn_the_page ===")
resp2 = {
    "tool_call": {
        "name": "ledger_turn_the_page",
        "args": {
            "checkpoint_summary": "Replaced pickle.dump in src/auth.py with json.dump.",
            "immediate_next_step": "Run pytest tests/test_auth.py to verify token validity.",
            "active_hypotheses": ["Redis connection might require bytes instead of str"]
        }
    }
}
print(agent.run_turn(resp2))

print(f"\nActive tokens after rollover: {agent.count_active_tokens()}")
print("\nTurn 0 Rehydration Seed:")
print(agent.messages[0]["content"])
