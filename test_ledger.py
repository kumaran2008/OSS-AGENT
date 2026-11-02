import time
from agent.memory.federated_ledger import SharedRootLedger, WorkerAgentScratchpad

workspace = "./workspace"

# 1. Initialize Root Ledger
root = SharedRootLedger(workspace, task_slug="refactor-auth")

# 2. Instantiate isolated subagents with their own scratchpads
builder = WorkerAgentScratchpad(root, agent_id="builder_01", role="builder")
tester = WorkerAgentScratchpad(root, agent_id="tester_01", role="tester")

# 3. Builder investigates private hypotheses without polluting Tester
builder.record_hypothesis("Session tokens are leaking through cache serialization")
builder.touch_file("src/auth/session.py")
builder.propose_invariant("Never use pickle for session serialization; use msgpack")

print("--- BUILDER PRIVATE PROMPT ---")
print(builder.build_context_prompt())

print("--- TESTER PROMPT (Notice Tester has NOT seen Builder's dirty state yet) ---")
print(tester.build_context_prompt())

# 4. Builder finishes phase and commits verified facts to the Root Ledger
builder.sync_to_root(verified_facts=["Session serialization is vulnerable in session.py:84"])

print("--- TESTER PROMPT AFTER BUILDER COMMITS TO ROOT ---")
print(tester.build_context_prompt())
