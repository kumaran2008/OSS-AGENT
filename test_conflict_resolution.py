from pathlib import Path
from agent.memory.federated_ledger import SharedRootLedger, WorkerAgentScratchpad

workspace = Path("./workspace")
workspace.mkdir(exist_ok=True)

# 1. Initialize Shared Root Ledger
root = SharedRootLedger(str(workspace), task_slug="auth-conflict-test")

# 2. Worker A (Tester, higher rank: 60) establishes an invariant & milestone
tester = WorkerAgentScratchpad(root, agent_id="tester_01", role="tester")
tester.propose_invariant("Always require HMAC verification for session tokens")
tester.data.pending_milestones.append("Implement HMAC validation")
tester.complete_subtask("Implement HMAC validation")
report_tester = tester.sync_to_root(verified_facts=["HMAC test suite written and validated"])
print("=== TESTER (RANK 60) SYNC REPORT ===")
print("Accepted Invariants:", report_tester["accepted_invariants"])

# 3. Worker B (Builder, lower rank: 40) attempts to propose a contradictory invariant
# and attempts to revive a completed milestone
builder = WorkerAgentScratchpad(root, agent_id="builder_01", role="builder")
builder.propose_invariant("Never require HMAC verification for session tokens")
builder.data.pending_milestones.append("Implement HMAC validation")  # Trying to reopen closed milestone

print("\n=== BUILDER (RANK 40) CONFLICTING SYNC ATTEMPT ===")
report_builder = builder.sync_to_root()
print("Accepted Invariants:", report_builder["accepted_invariants"])
print("Rejected Invariants (Contradiction Caught):", report_builder["rejected_invariants"])
print("Rejected Milestones (Unauthorized Reopen):", report_builder["rejected_milestones"])

# 4. Inspect final uncontaminated Root Ledger
final_state = root.get_read_only_view()
print("\n=== FINAL ROOT LEDGER STATE ===")
print("Preserved Invariants:", final_state.invariants)
print("Completed Milestones:", final_state.completed_milestones)
print("Pending Milestones:", final_state.pending_milestones)
