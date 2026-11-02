import asyncio
import subprocess
import shutil
import time
from pathlib import Path

from agent.pa_scaffolder.pty_sandbox import InteractiveSandboxSession
from agent.pa_scaffolder.workspace_orchestrator import WorkspaceOrchestrator
from agent.pa_scaffolder.rooms_engine import RoomsEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_workspace_orchestrator():
    print("=" * 70)
    print("     WORKSPACE ORCHESTRATOR & MULTI-FILE TRANSACTION BENCHMARK")
    print("=" * 70)

    test_ws = Path("workspace/test_orch_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    orchestrator = WorkspaceOrchestrator(test_ws)

    # -------------------------------------------------------------------------
    # 1. Device Workspace Profiling
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Device Workspace Profiling...")
    prof = orchestrator.profile
    print(f" • Host Environment:  {'Android Termux' if prof.is_termux else 'Desktop / Laptop'}")
    print(f" • Has GUI Display:   {prof.has_gui}")
    print(f" • Detected Editors:  {prof.detected_editors if prof.detected_editors else 'Terminal standard'}")

    ok_ed, ed_msg = orchestrator.open_in_editor("README.md", line_number=1)
    (test_ws / "README.md").write_text("# Test\n", encoding="utf-8")
    ok_ed, ed_msg = orchestrator.open_in_editor("README.md", line_number=1)
    print(f" • Editor Dispatch:   \"{ed_msg}\"")
    assert ok_ed is True
    print(" >>> CRITERION 1 PASSED: Device workspace profiling active. <<<")

    # -------------------------------------------------------------------------
    # 2. Multi-File Atomic Transactions & Syntax Rollback Guard
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing Multi-File Atomic Patch with Syntax Rollback...")
    (test_ws / "mod_a.py").write_text("# Original A\n", encoding="utf-8")
    (test_ws / "mod_b.py").write_text("# Original B\n", encoding="utf-8")

    # Test broken transaction: mod_a has valid code, mod_b has a SyntaxError
    broken_transaction = {
        "mod_a.py": "def valid_func(): return True\n",
        "mod_b.py": "def broken_syntax(: return False\n"  # Syntax error
    }

    t0 = time.perf_counter()
    ok_fail, err_msg, touched = orchestrator.atomic_multi_file_patch(broken_transaction)
    t_check_ms = (time.perf_counter() - t0) * 1000.0

    print(f" • Syntax Pre-Flight Time: {t_check_ms:.2f} ms")
    print(f" • Transaction Status:     {'ACCEPTED' if ok_fail else 'REJECTED (Correct)'}")
    print(f" • Rejection Reason:       {err_msg.splitlines()[0]}")

    assert ok_fail is False
    assert "Syntax Pre-Flight Failed" in err_msg
    # Verify mod_a was NOT modified (Atomic rollback)
    assert (test_ws / "mod_a.py").read_text(encoding="utf-8") == "# Original A\n"

    # Test valid multi-file transaction
    valid_transaction = {
        "mod_a.py": "def func_a(): return 10\n",
        "mod_b.py": "def func_b(): return 20\n"
    }
    ok_valid, succ_msg, touched_valid = orchestrator.atomic_multi_file_patch(valid_transaction)
    print(f" • Valid Transaction:      {succ_msg}")
    assert ok_valid is True
    assert len(touched_valid) == 2
    assert "return 10" in (test_ws / "mod_a.py").read_text(encoding="utf-8")
    assert "return 20" in (test_ws / "mod_b.py").read_text(encoding="utf-8")
    print(" >>> CRITERION 2 PASSED: Multi-file atomic transaction & syntax rollback verified. <<<")

    # -------------------------------------------------------------------------
    # 3. Local Dev Server Health Probing
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing Background Dev Server Health Probing...")
    pty = InteractiveSandboxSession(workspace_root=str(test_ws))

    # Pick a high port to avoid conflicts
    test_port = 8991
    # Start a background daemon
    pty.start_daemon("test_http_srv", f"python -m http.server {test_port}")

    # Probe port
    ok_probe, probe_msg = orchestrator.probe_service_health(port=test_port, timeout_sec=6.0)
    print(f" • Probe Result:          \"{probe_msg}\"")
    assert ok_probe is True

    # Stop daemon
    pty.stop_daemon("test_http_srv")
    pty.close()
    print(" >>> CRITERION 3 PASSED: Dev server health probe verified. <<<")

    # -------------------------------------------------------------------------
    # 4. Autonomous Task with Multi-File Coordinated Patching
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing Autonomous Task with Multi-File Coordinated Patching...")
    # Initialize real Git repo
    subprocess.run(["git", "init"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "config", "user.name", "OrchAgent"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "config", "user.email", "orch@agent.local"], cwd=str(test_ws), capture_output=True)

    # Buggy multi-file setup: service.py calls calculate() in calc.py with wrong arguments
    (test_ws / "calc.py").write_text("def calculate(x, y):\n    return x + y\n", encoding="utf-8")
    (test_ws / "service.py").write_text("from calc import calculate\ndef execute():\n    return calculate(10)  # TypeError: missing y\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init baseline"], cwd=str(test_ws), capture_output=True)

    reproduce_script = (
        "import sys\n"
        "from service import execute\n"
        "try:\n"
        "    res = execute()\n"
        "    assert res == 15\n"
        "    sys.exit(0)\n"
        "except Exception as e:\n"
        "    print(f'CRASH: {e}')\n"
        "    sys.exit(1)\n"
    )

    def multi_file_solver(task_desc, err_log):
        # Coordinated fix across both files
        return {
            "calc.py": "def calculate(x, y=5):\n    return x + y\n",
            "service.py": "from calc import calculate\ndef execute():\n    return calculate(10, 5)\n"
        }

    engine = RoomsEngine(workspace_root=str(test_ws))
    task_pty = InteractiveSandboxSession(workspace_root=str(test_ws))

    res_auto = await engine.execute_builder_task(
        task_description="Fix TypeError in service.py calling calculate in calc.py",
        reproduce_code=reproduce_script,
        patch_solver_fn=multi_file_solver,
        pty_session=task_pty,
        user_persona="engineer"
    )

    print(f" • Multi-File Task Status: {res_auto.status}")
    print(f" • Attempts to Green:     {res_auto.attempts_taken}")
    print(f" • Shadow Branch:         {res_auto.shadow_branch}")
    assert res_auto.success is True
    assert res_auto.status == "GREEN_VERIFIED"
    assert "calculate(10, 5)" in (test_ws / "service.py").read_text(encoding="utf-8")
    task_pty.close()
    print(" >>> CRITERION 4 PASSED: Autonomous task coordinated multi-file patch to green. <<<")

    # -------------------------------------------------------------------------
    # 5. Tool Registry Integration
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing ToolRegistry Dispatch of Workspace Orchestrator Tools...")
    tools = ToolRegistry(workspace_root=str(test_ws))

    res_tool = await tools.dispatch("workspace_open_editor", {"file_path": "service.py", "line_number": 3})
    print(f" • Tool Dispatch Output:  \"{res_tool.output}\"")
    assert res_tool.success is True

    tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> WORKSPACE ORCHESTRATOR & MULTI-FILE ENGINE FULLY VERIFIED <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_workspace_orchestrator())
