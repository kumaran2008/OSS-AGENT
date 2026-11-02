from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from agent.kernel.sandbox_isolation import sandbox_executor


@dataclass
class SimulationRunResult:
    script_path: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    verified_numerical_result: bool


class PythonSimulationLaboratory:
    """Section 6.5: In-Laptop Empirical Simulation Lab (NumPy, SciPy, stats verification)."""

    STAGING_DIR = Path("workspace/.research_simulations")

    def __init__(self):
        self.STAGING_DIR.mkdir(parents=True, exist_ok=True)

    async def execute_empirical_simulation(self, script_name: str, python_code: str, timeout_sec: float = 5.0) -> SimulationRunResult:
        t0 = time.perf_counter()
        f_path = self.STAGING_DIR / script_name
        f_path.write_text(python_code, encoding="utf-8")

        res = await sandbox_executor.run_warm_python_script(f_path, python_code, timeout_sec=timeout_sec)
        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        numerical_ok = (res.exit_code == 0 and "Traceback" not in res.stderr and "AssertionError" not in res.stderr)

        return SimulationRunResult(
            script_path=str(f_path),
            exit_code=res.exit_code,
            stdout=res.stdout,
            stderr=res.stderr,
            duration_ms=dur,
            verified_numerical_result=numerical_ok,
        )


simulation_lab = PythonSimulationLaboratory()
