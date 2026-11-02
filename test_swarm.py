from agent.orchestrator.swarm import SwarmOrchestrator

# Initialize multi-agent coordinator
swarm = SwarmOrchestrator(
    workspace_root="./workspace",
    task_slug="auth-system",
    token_ceiling=3000
)

# Phase 1: Builder Agent writes code and records invariant
builder_actions = [
    {
        "tool_call": {
            "name": "ledger_record_invariant",
            "args": {
                "invariant": "All session tokens must expire after 3600 seconds",
                "rationale": "Security compliance"
            }
        }
    },
    {
        "tool_call": {
            "name": "ledger_manage_milestones",
            "args": {
                "action": "add",
                "milestone": "Verify token expiration via automated unit tests"
            }
        }
    }
]

swarm.run_pipeline_step(
    role="builder",
    instructions="Implement token session handling logic.",
    simulated_actions=builder_actions
)

# Phase 2: Tester Agent activates and verifies state
tester_actions = [
    {
        "tool_call": {
            "name": "ledger_manage_milestones",
            "args": {
                "action": "complete",
                "milestone": "Verify token expiration via automated unit tests"
            }
        }
    }
]

swarm.run_pipeline_step(
    role="tester",
    instructions="Run test assertions against token expiration.",
    simulated_actions=tester_actions
)

# Check the final shared state
final_state = swarm.root_ledger.get_read_only_view()
print("\n=== FINAL ROOT LEDGER STATE ===")
print(f"Invariants: {final_state.invariants}")
print(f"Completed Milestones: {final_state.completed_milestones}")
print(f"Active Workers: {list(final_state.active_workers.keys())}")
