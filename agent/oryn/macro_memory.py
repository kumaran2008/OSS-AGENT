from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.workflow_runtime import GuardedMacroRecipe, workflow_runtime
from agent.oryn.action_executor import oryn_action_executor
from agent.oryn.contracts import ActionBatch, ComputerAction
from agent.oryn.runtime import oryn_runtime


class ORYNTaskMacroMemory:
    """Milestone 7: Task Memory & GuardedMacroRecipe Auto-Promotion Engine.

    Records verified multi-step ORYN execution sequences into SQLite and mounts
    them into `workflow_runtime._macros` so recurring procedures execute in
    System 1 with zero LLM calls while still checking live layout fingerprints.
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self) -> None:
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._hydrate_macros_into_workflow_runtime()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oryn_task_macro_memory (
                    capability_key TEXT PRIMARY KEY,
                    macro_id TEXT NOT NULL,
                    app_identity TEXT NOT NULL,
                    route_pattern TEXT NOT NULL,
                    version_fingerprint TEXT NOT NULL,
                    preconditions_json TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    expected_postconditions_json TEXT NOT NULL,
                    verified_runs INTEGER DEFAULT 1,
                    median_latency_ms REAL DEFAULT 0.0,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _hydrate_macros_into_workflow_runtime(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM oryn_task_macro_memory").fetchall()
            for r in rows:
                recipe = GuardedMacroRecipe(
                    macro_id=r["macro_id"],
                    app_identity=r["app_identity"],
                    route_pattern=r["route_pattern"],
                    version_fingerprint=r["version_fingerprint"],
                    preconditions=json.loads(r["preconditions_json"]),
                    steps=json.loads(r["steps_json"]),
                    expected_postconditions=json.loads(r["expected_postconditions_json"]),
                    verified_runs=int(r["verified_runs"]),
                    invalidated=False,
                )
                workflow_runtime._macros[r["capability_key"]] = recipe

    @fault_recorder.guard(subsystem="oryn.macro_memory")
    def promote_verified_batch_to_macro(
        self,
        capability_key: str,
        app_identity: str,
        actions: List[ComputerAction],
        batch_result: Dict[str, Any],
        version_fingerprint: str = "oryn_v1",
    ) -> Optional[GuardedMacroRecipe]:
        """Promotes a verified ActionBatch into a reusable GuardedMacroRecipe."""
        if not batch_result.get("verified"):
            return None

        serialized_steps: List[Dict[str, Any]] = []
        for act in actions:
            serialized_steps.append(
                {
                    "channel": act.channel,
                    "operation": act.operation,
                    "target_ref": act.target_ref,
                    "coordinates": list(act.coordinates) if act.coordinates else None,
                    "coordinate_space": act.coordinate_space,
                    "text": act.text,
                    "keys": list(act.keys),
                    "wait_ms": act.wait_ms,
                    "payload": act.payload,
                }
            )

        seed = f"{capability_key}|{app_identity}|{len(actions)}"
        macro_id = f"macro_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}"
        preconds = ["target_app_reachable", "layout_fingerprint_valid"]
        postconds = ["all_steps_verified", "zero_unexpected_modals"]
        dur_ms = float(batch_result.get("duration_ms", 0.0))

        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute(
                "SELECT verified_runs FROM oryn_task_macro_memory WHERE capability_key = ?",
                (capability_key,),
            ).fetchone()
            runs = (int(row[0]) + 1) if row else 1
            conn.execute(
                """
                INSERT OR REPLACE INTO oryn_task_macro_memory (
                    capability_key, macro_id, app_identity, route_pattern,
                    version_fingerprint, preconditions_json, steps_json,
                    expected_postconditions_json, verified_runs, median_latency_ms, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capability_key,
                    macro_id,
                    app_identity,
                    capability_key,
                    version_fingerprint,
                    json.dumps(preconds),
                    json.dumps(serialized_steps),
                    json.dumps(postconds),
                    runs,
                    dur_ms,
                    time.time(),
                ),
            )
            conn.commit()

        recipe = GuardedMacroRecipe(
            macro_id=macro_id,
            app_identity=app_identity,
            route_pattern=capability_key,
            version_fingerprint=version_fingerprint,
            preconditions=preconds,
            steps=serialized_steps,
            expected_postconditions=postconds,
            verified_runs=runs,
            invalidated=False,
        )
        workflow_runtime._macros[capability_key] = recipe
        return recipe

    @fault_recorder.guard(subsystem="oryn.macro_memory")
    async def replay_macro_if_available(
        self,
        capability_key: str,
        current_fingerprint: str = "oryn_v1",
    ) -> Optional[Dict[str, Any]]:
        """Replays a stored GuardedMacroRecipe through ORYN with 0 LLM calls."""
        recipe = workflow_runtime.get_macro(capability_key, current_fingerprint=current_fingerprint)
        if recipe is None:
            return None

        rid = oryn_runtime.primary_runtime.runtime_id
        reconstructed: List[ComputerAction] = []
        for idx, step in enumerate(recipe.steps):
            coords_raw = step.get("coordinates")
            coords = (int(coords_raw[0]), int(coords_raw[1])) if coords_raw else None
            reconstructed.append(
                ComputerAction(
                    action_id=f"{recipe.macro_id}_s{idx+1}",
                    runtime_id=rid,
                    channel=step.get("channel", "dom"),
                    operation=step.get("operation", "click"),
                    target_ref=step.get("target_ref"),
                    coordinates=coords,
                    coordinate_space=step.get("coordinate_space", "NATIVE_DESKTOP_PX"),
                    text=step.get("text"),
                    keys=tuple(step.get("keys", ())),
                    wait_ms=int(step.get("wait_ms", 0)),
                    payload=dict(step.get("payload", {})),
                )
            )

        batch = ActionBatch(
            batch_id=f"replay_{recipe.macro_id}_{int(time.time() * 1000)}",
            runtime_id=rid,
            actions=reconstructed,
        )
        res = await oryn_action_executor.execute_batch(batch)
        res["macro_id"] = recipe.macro_id
        res["llm_calls_used"] = 0
        return res


oryn_macro_memory = ORYNTaskMacroMemory()
