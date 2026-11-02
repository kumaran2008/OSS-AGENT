import os
from pathlib import Path
from agent.orchestrator.swarm import SwarmOrchestrator

# Setup clean workspace
workspace = Path("./workspace")
workspace.mkdir(exist_ok=True)

# Create a sample Python file with valid syntax
valid_file = workspace / "valid_code.py"
with open(valid_file, "w") as f:
    f.write("def calculate(x):\n    return x * 2\n")

# Create a sample Python file with syntax errors
broken_file = workspace / "broken_code.py"
with open(broken_file, "w") as f:
    f.write("def broken_func(\n    return 42\n")

swarm = SwarmOrchestrator(workspace_root=str(workspace), task_slug="validator-test")

# -------------------------------------------------------------
# Case 1: Bad PR (Syntax Error, Nonexistent file, Speculative Invariant)
# -------------------------------------------------------------
print("=== CASE 1: SUBMITTING DEFECTIVE WORKER PR ===")
bad_actions = [
    {
        "tool_call": {
            "name": "ledger_record_invariant",
            "args": {
                "invariant": "Maybe assume this database connection works",
                "rationale": "Testing"
            }
        }
    }
]

worker = swarm.get_or_create_worker("builder", "Build code")
worker.worker.touch_file("broken_code.py")
worker.worker.touch_file("ghost_file.py")

success = swarm.run_pipeline_step(
    role="builder",
    instructions="Write routines",
    simulated_actions=bad_actions
)
print(f"Result: Approved={success}")

# -------------------------------------------------------------
# Case 2: Clean PR (Valid Syntax, Real File, Sound Invariant)
# -------------------------------------------------------------
print("\n=== CASE 2: SUBMITTING VALID WORKER PR ===")
worker.worker.data.files_touched.clear()
worker.worker.data.candidate_invariants.clear()
worker.worker.touch_file("valid_code.py")

clean_actions = [
    {
        "tool_call": {
            "name": "ledger_record_invariant",
            "args": {
                "invariant": "All calculate functions must return numeric types",
                "rationale": "Prevents downstream type cast errors"
            }
        }
    }
]

success = swarm.run_pipeline_step(
    role="builder",
    instructions="Write routines",
    simulated_actions=clean_actions,
    verified_facts=["All unit tests passed for valid_code.py"]
)
print(f"Result: Approved={success}")

# Verify Root Ledger state
final_state = swarm.root_ledger.get_read_only_view()
print("\n=== FINAL ROOT LEDGER STATE ===")
print("Invariants:", final_state.invariants)
print("Modified Artifacts:", final_state.modified_artifacts)
