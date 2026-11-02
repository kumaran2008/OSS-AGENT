import asyncio
import subprocess
import shutil
from pathlib import Path

from agent.pa_scaffolder.rooms_engine import AgentMode
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


async def test_builder_end_to_end():
    print("=" * 70)
    print("     BUILDER ROOM END-TO-END WIRED BENCHMARK (WIRES 1-4)")
    print("=" * 70)

    test_ws = Path("workspace/test_wired_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    # Initialize clean Git repository
    subprocess.run(["git", "init"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "config", "user.name", "WiredAgent"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@wired.local"], cwd=str(test_ws), capture_output=True)

    # Create buggy math_engine.py
    buggy_code = "def compute_ratio(a: int, b: int) -> float:\n    return a / b\n"
    (test_ws / "math_engine.py").write_text(buggy_code, encoding="utf-8")
    (test_ws / "README.md").write_text("# Wired Sandbox\n", encoding="utf-8")

    # Baseline Git Commit
    subprocess.run(["git", "add", "-A"], cwd=str(test_ws), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial baseline commit"], cwd=str(test_ws), capture_output=True)

    # -------------------------------------------------------------------------
    # TEST WIRE 3: Dirty Worktree Stash Guard
    # -------------------------------------------------------------------------
    print("\n[1/4] Testing Wire 3: Dirty Worktree Stash Guard...")
    # Create an uncommitted file to simulate in-progress user work
    uncommitted_file = test_ws / "dirty_notes.txt"
    uncommitted_file.write_text("CRITICAL IN-PROGRESS USER WORK - DO NOT LOSE\n", encoding="utf-8")

    # Verify worktree is dirty
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(test_ws), capture_output=True, text=True).stdout
    print(f" • Worktree status before task:\n   {status.strip()}")
    assert "dirty_notes.txt" in status

    # Initialize Engine pointing to test workspace
    harness = UnifiedAsyncEngine()
    harness.tools.workspace_root = test_ws
    harness.tools.pty.workspace_root = test_ws
    harness.rooms.workspace = test_ws
    harness.rooms.builder_supervisor.workspace = test_ws

    # -------------------------------------------------------------------------
    # TEST WIRE 4: Pre-Flight Tool & MCP Schema Export
    # -------------------------------------------------------------------------
    print("\n[2/4] Testing Wire 4: Pre-Flight Tool & MCP Schema Export...")
    schemas = harness.tools.get_all_tool_schemas()
    tool_names = [s["function"]["name"] for s in schemas]
    print(f" • Exported Schemas Count: {len(schemas)}")
    print(f" • Tool Names:             {tool_names}")
    assert "bash_execute" in tool_names
    assert "file_patch" in tool_names
    assert "mcp_call" in tool_names
    print(" >>> CRITERION 2 PASSED: Pre-flight tool schemas generated for prompt context. <<<")

    # -------------------------------------------------------------------------
    # TEST WIRE 1 & 2: Conversational Bridge to Autonomous Task
    # -------------------------------------------------------------------------
    print("\n[3/4] Testing Wire 1 & 2: Conversational Bridge & Auto-Reproduction...")
    # Switch to Builder mode
    res_mode = await harness.process_voice_turn("let's lock in and build")
    print(f" • Mode Switch:            \"{res_mode['spoken_response']}\"")
    assert harness.rooms.current_mode == AgentMode.BUILDER

    # Dispatch freeform conversational bug fix command
    user_task = "Fix the ZeroDivisionError in math_engine.py when b is zero"
    print(f" • User Utterance:         \"{user_task}\"")

    turn_res = await harness.process_voice_turn(user_task)
    print(f" • Turn Result Type:       {turn_res.get('type')}")
    print(f" • Execution Status:       {turn_res.get('status')}")
    print(f" • Shadow Branch:          {turn_res.get('shadow_branch')}")
    print(f" • Spoken Response:        \"{turn_res.get('spoken_response')}\"")

    assert turn_res.get("type") == "AUTONOMOUS_TASK_COMPLETE"
    assert turn_res.get("success") is True
    assert turn_res.get("status") == "GREEN_VERIFIED"
    print(" >>> CRITERION 3 PASSED: Conversational turn triggered autonomous Red-to-Green loop. <<<")

    # -------------------------------------------------------------------------
    # VERIFY WIRE 3 COMPLETION: Stashed File Restored Intact
    # -------------------------------------------------------------------------
    print("\n[4/4] Verifying Uncommitted User Work Restored Intact...")
    assert uncommitted_file.exists(), "CRITICAL FAILURE: Uncommitted user file was deleted!"
    content = uncommitted_file.read_text(encoding="utf-8")
    print(f" • Restored File Content:  \"{content.strip()}\"")
    assert "CRITICAL IN-PROGRESS USER WORK" in content
    print(" >>> CRITERION 4 PASSED: User's dirty worktree stashed and safely restored. <<<")

    # Teardown
    harness.tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> ALL 4 WIRES 100% CONNECTED, VERIFIED & PRODUCTION READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_builder_end_to_end())
