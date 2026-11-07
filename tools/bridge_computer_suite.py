from __future__ import annotations

import ast
from pathlib import Path

suite_path = Path("agent/suites/computer_app_control.py")
if not suite_path.exists():
    raise FileNotFoundError("agent/suites/computer_app_control.py not found!")

source = suite_path.read_text(encoding="utf-8")
tree = ast.parse(source)

print("=== Existing Structure of agent/suites/computer_app_control.py ===")
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        print(f"Class: {node.name} -> Methods: {methods}")

bridge_marker = "# === ORYN_NON_DESTRUCTIVE_SUITE_BRIDGE ==="

bridge_code = """

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


for _cls_name, _cls_obj in list(globals().items()):
    if isinstance(_cls_obj, type) and "Computer" in _cls_name:
        if not hasattr(_cls_obj, "execute_computer_objective"):
            setattr(_cls_obj, "execute_computer_objective", _oryn_execute_computer_objective)
        if not hasattr(_cls_obj, "execute_action_batch"):
            setattr(_cls_obj, "execute_action_batch", _oryn_execute_action_batch)
"""

if bridge_marker not in source:
    suite_path.write_text(source.rstrip() + "\n" + bridge_code, encoding="utf-8")
    print("[ORYN Bridge]: Attached execute_computer_objective & execute_action_batch non-destructively!")
else:
    print("[ORYN Bridge]: Already attached!")
