import asyncio
import subprocess
import shutil
from pathlib import Path

from agent.pa_scaffolder.pty_sandbox import InteractiveSandboxSession
from agent.pa_scaffolder.rooms_engine import RoomsEngine, TaskResult


async def test_master_autonomous_loop():
    print("=" * 70)
    print("     MASTER AUTONOMOUS TASK WORKFLOW VERIFICATION BENCHMARK")
    print("=" * 70)

    test_ws = Path("workspace/test_autonomous_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    # Initialize a real Git repository in the sandbox
    subprocess.run(["git", "init"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "config", "user.name", "AgentTest"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=str(test_ws), capture_output=True)

    # Create buggy math_engine.py
    buggy_code = (
        "def compute_ratio(a: int, b: int) -> float:\n"
        "    return a / b  # Bug: ZeroDivisionError when b == 0\n"
    )
    (test_ws / "math_engine.py").write_text(buggy_code, encoding="utf-8")
    (test_ws / "README.md").write_text("# Math Engine\n", encoding="utf-8")

    # Baseline commit
    subprocess.run(["git", "add", "-A"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial baseline commit"], cwd=str(test_ws), capture_output=True)

    engine = RoomsEngine(workspace_root=str(test_ws))
    pty = InteractiveSandboxSession(workspace_root=str(test_ws))

    # -------------------------------------------------------------------------
    # 1. Anti-Assumption Gate Test
    # -------------------------------------------------------------------------
    print("\n[1/4] Testing Anti-Assumption Interactive Gate...")
    res_ambiguous = await engine.execute_builder_task(
        task_description="build an application with user authentication",
        reproduce_code="",
        patch_solver_fn=lambda t, e: None,
        pty_session=pty
    )

    print(f" • Gate Status:           {res_ambiguous.status}")
    print(f" • Clarification Question: \"{res_ambiguous.clarification_question}\"")
    assert res_ambiguous.status == "NEEDS_CLARIFICATION"
    assert res_ambiguous.clarification_question is not None
    print(" >>> CRITERION 1 PASSED: Ambiguous tasks stopped before mutating disk. <<<")

    # -------------------------------------------------------------------------
    # 2. Red-to-Green Reproduction & Autonomous Fix
    # -------------------------------------------------------------------------
    print("\n[2/4] Testing Red-to-Green Autonomous Fix Cycle...")
    reproduce_script = (
        "import sys\n"
        "from math_engine import compute_ratio\n"
        "try:\n"
        "    res = compute_ratio(10, 0)\n"
        "    assert res == 0.0\n"
        "    sys.exit(0)  # GREEN\n"
        "except Exception as e:\n"
        "    print(f'CRASH: {e}')\n"
        "    sys.exit(1)  # RED\n"
    )

    fixed_code = (
        "def compute_ratio(a: int, b: int) -> float:\n"
        "    if b == 0:\n"
        "        return 0.0\n"
        "    return a / b\n"
    )

    def mock_patch_solver(task_desc: str, err_log: str):
        # Solves the bug
        return ("math_engine.py", fixed_code)

    res_green = await engine.execute_builder_task(
        task_description="Fix ZeroDivisionError in compute_ratio when b is 0",
        reproduce_code=reproduce_script,
        patch_solver_fn=mock_patch_solver,
        pty_session=pty,
        user_persona="engineer"
    )

    print(f" • Execution Status:      {res_green.status}")
    print(f" • Attempts to Green:     {res_green.attempts_taken}")
    print(f" • Active Shadow Branch:  {res_green.shadow_branch}")
    print(f" • Report Summary:        \"{res_green.report}\"")

    assert res_green.success is True
    assert res_green.status == "GREEN_VERIFIED"
    assert res_green.shadow_branch is not None
    assert (test_ws / "math_engine.py").read_text(encoding="utf-8") == fixed_code
    print(" >>> CRITERION 2 PASSED: RED reproduced, patch applied, GREEN verified and committed. <<<")

    # -------------------------------------------------------------------------
    # 3. Anti-Loop Circuit Breaker in Autonomous Action
    # -------------------------------------------------------------------------
    print("\n[3/4] Testing Anti-Loop SHA-256 Circuit Breaker & Safe Rollback...")
    broken_code = "def compute_ratio(a, b): raise RuntimeError('Persistent Crash')\n"
    (test_ws / "math_engine.py").write_text(broken_code, encoding="utf-8")

    def broken_patch_solver(task_desc: str, err_log: str):
        # Returns a patch that still fails with the identical trace
        return ("math_engine.py", broken_code)

    res_breaker = await engine.execute_builder_task(
        task_description="Fix persistent runtime error",
        reproduce_code=reproduce_script,
        patch_solver_fn=broken_patch_solver,
        pty_session=pty,
        user_persona="engineer"
    )

    print(f" • Breaker Status:        {res_breaker.status}")
    print(f" • Attempts Before Trip:  {res_breaker.attempts_taken}")
    print(f" • Error Summary:         \"{res_breaker.error_summary}\"")

    assert res_breaker.success is False
    assert res_breaker.status == "CIRCUIT_BREAKER_TRIPPED"
    print(" >>> CRITERION 3 PASSED: Recurring traceback tripped circuit breaker and halted loop. <<<")

    # -------------------------------------------------------------------------
    # 4. Dual-Persona Adaptive Report Formatting
    # -------------------------------------------------------------------------
    print("\n[4/4] Testing Dual-Persona Adaptive Translation...")
    supervisor = engine.builder_supervisor
    crash_trace = "IndexError: list index out of range on line 88"

    founder_rep = supervisor.format_adaptive_explanation(crash_trace, user_persona="founder")
    engineer_rep = supervisor.format_adaptive_explanation(crash_trace, user_persona="engineer")

    print(f" • Founder Report:        \"{founder_rep}\"")
    print(f" • Engineer Report:       \"{engineer_rep}\"")

    assert "IndexError" not in founder_rep
    assert "IndexError" in engineer_rep
    print(" >>> CRITERION 4 PASSED: Reports dynamically adapt between executive and technical audiences. <<<")

    # Cleanup
    pty.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> MASTER AUTONOMOUS TASK WORKFLOW 100% OPERATIONAL & VERIFIED <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_master_autonomous_loop())
