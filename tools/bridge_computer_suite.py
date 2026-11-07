from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

suite_path = REPO_ROOT / "agent/suites/computer_app_control.py"
source = suite_path.read_text(encoding="utf-8")

marker = "# === ORYN_NON_DESTRUCTIVE_SUITE_BRIDGE ==="
if marker in source:
    source = source.split(marker)[0].rstrip()

tree = ast.parse(source)
print("=== Existing Classes & Methods in agent/suites/computer_app_control.py ===")
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        methods = [
            n.name for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        print(f"  Class: {node.name} -> {methods}")

bridge_block = '''

# === ORYN_NON_DESTRUCTIVE_SUITE_BRIDGE ===
async def _oryn_execute_computer_objective(
    self,
    user_objective: str,
    target_app: str = "workstation",
    preferred_channel: str | None = None,
    operation: str = "invoke_api",
    target_ref: str | None = None,
    text: str | None = None,
    payload: dict | None = None,
) -> dict:
    from agent.kernel.computer_control import computer_control_broker
    return await computer_control_broker.execute_oryn_action(
        user_objective=user_objective,
        target_app=target_app,
        preferred_channel=preferred_channel,
        operation=operation,
        target_ref=target_ref,
        text=text,
        payload=payload,
    )


async def _oryn_execute_action_batch(
    self,
    actions: list,
    halt_on_modal: bool = True,
) -> dict:
    import time
    from agent.oryn.action_executor import oryn_action_executor
    from agent.oryn.contracts import ActionBatch
    from agent.oryn.runtime import oryn_runtime

    batch = ActionBatch(
        batch_id=f"batch_{int(time.time() * 1000)}",
        runtime_id=oryn_runtime.primary_runtime.runtime_id,
        actions=actions,
        halt_on_unexpected_modal=halt_on_modal,
    )
    return await oryn_action_executor.execute_batch(batch)


for _k, _v in list(globals().items()):
    if isinstance(_v, type) and ("Computer" in _k or "Suite" in _k):
        setattr(_v, "execute_computer_objective", _oryn_execute_computer_objective)
        setattr(_v, "execute_action_batch", _oryn_execute_action_batch)

if "computer_app_control_suite" in globals():
    _inst = globals()["computer_app_control_suite"]
    setattr(_inst.__class__, "execute_computer_objective", _oryn_execute_computer_objective)
    setattr(_inst.__class__, "execute_action_batch", _oryn_execute_action_batch)
'''

suite_path.write_text(source + "\n" + bridge_block, encoding="utf-8")
print("[ORYN Bridge]: Successfully wired into UniversalComputerAppControlSuite!")
