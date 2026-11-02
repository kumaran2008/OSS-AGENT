import asyncio
import time
from pathlib import Path

from agent.pa_scaffolder.agent_config import AgentConfig
from agent.pa_scaffolder.pty_sandbox import InteractiveSandboxSession
from agent.pa_scaffolder.code_patcher import ASTCodePatcher
from agent.pa_scaffolder.desktop_hal import NativeDesktopHAL
from agent.pa_scaffolder.tool_registry import ToolRegistry, ToolResult
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


async def test_pillar2():
    config = AgentConfig()
    active_agent_name = config.agent_name.upper()

    print("=" * 70)
    print(f"     PILLAR 2 VERIFICATION: THE EXECUTION ENGINE ('THE HANDS')")
    print(f"     [Active Persona Name: '{config.agent_name}']")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. Verify Interactive PTY Sandbox Execution & State Persistence
    # -------------------------------------------------------------------------
    print("\n[1/4] Testing Interactive PTY Shell Sandbox (State & Streaming)...")
    sandbox = InteractiveSandboxSession()

    test_flag_val = f"{active_agent_name}_SYSTEM_ONLINE"

    # Command 1: Set persistent environment variable
    code1, out1 = await sandbox.execute_and_collect(f"export OSS_TEST_FLAG='{test_flag_val}'")
    print(f" • Set Env Var 'OSS_TEST_FLAG' to '{test_flag_val}' (Exit: {code1})")

    # Command 2: Read it back to prove persistent state in same shell
    code2, out2 = await sandbox.execute_and_collect("echo $OSS_TEST_FLAG")
    print(f" • Read Back Value: \"{out2.strip()}\" (Exit: {code2})")
    assert test_flag_val in out2, f"Failed state persistence! Expected '{test_flag_val}', got: '{out2}'"

    # Command 3: Multi-line Python execution in shell
    code3, out3 = await sandbox.execute_and_collect("python -c 'print(40 + 2)'")
    print(f" • Executed Python Expression: \"{out3.strip()}\" (Exit: {code3})")
    assert "42" in out3

    sandbox.terminate()
    print(" >>> CRITERION 1 PASSED: PTY Sandbox interactive streaming verified. <<<")

    # -------------------------------------------------------------------------
    # 2. Verify AST Code Patcher (Fuzzy Offset Matching & Syntax Rollback)
    # -------------------------------------------------------------------------
    print("\n[2/4] Testing AST Code Patcher with Shifted Line Numbers...")
    test_src_path = Path("workspace/test_target_module.py")
    test_src_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate 50 lines of mock code
    initial_code = "\n".join([f"# Header comment line {i}" for i in range(1, 25)])
    initial_code += "\n\ndef compute_metrics(x, y):\n    result = x + y\n    return result\n"
    initial_code += "\n".join([f"# Footer comment line {i}" for i in range(25, 45)]) + "\n"
    test_src_path.write_text(initial_code, encoding="utf-8")

    # Patch 1: Diff with shifted header lines (claiming line 10 instead of 26)
    shifted_diff = (
        "@@ -10,3 +10,4 @@\n"
        " def compute_metrics(x, y):\n"
        "-    result = x + y\n"
        "+    # Added performance guard\n"
        "+    result = (x + y) * 2\n"
        "     return result\n"
    )

    ok, msg = ASTCodePatcher.patch_file(str(test_src_path), shifted_diff)
    print(f" • Fuzzy Patch Result: {ok} | \"{msg}\"")
    assert ok is True
    updated_code = test_src_path.read_text(encoding="utf-8")
    assert "result = (x + y) * 2" in updated_code

    # Patch 2: Corrupt diff targeting the updated file context (Must reject on AST syntax)
    corrupt_diff = (
        "@@ -10,5 +10,5 @@\n"
        " def compute_metrics(x, y):\n"
        "     # Added performance guard\n"
        "-    result = (x + y) * 2\n"
        "+    result = (x + y *  # Missing closing parenthesis!\n"
        "     return result\n"
    )
    ok_bad, msg_bad = ASTCodePatcher.patch_file(str(test_src_path), corrupt_diff)
    print(f" • Corrupt Patch Rejected: {not ok_bad} | \"{msg_bad[:60]}...\"")
    assert ok_bad is False
    assert "Syntax corruption" in msg_bad or "SyntaxError" in msg_bad
    # Verify file was rolled back and preserved
    assert "result = (x + y) * 2" in test_src_path.read_text(encoding="utf-8")

    test_src_path.unlink(missing_ok=True)
    print(" >>> CRITERION 2 PASSED: Fuzzy AST patching & safety rollback verified. <<<")

    # -------------------------------------------------------------------------
    # 3. Verify Desktop OS Automation HAL
    # -------------------------------------------------------------------------
    print("\n[3/4] Testing Native Desktop OS HAL...")
    desktop = NativeDesktopHAL()
    test_clip_payload = f"oss-agent-{config.agent_name.lower()}-test-1337"
    clip_ok = desktop.set_clipboard(test_clip_payload)
    read_clip = desktop.get_clipboard()
    print(f" • Clipboard Written: {clip_ok} | Retrieved: \"{read_clip.strip()}\"")
    assert test_clip_payload in read_clip

    # Window focus attempt (must return bool without throwing)
    focus_res = desktop.bring_window_to_front("NonExistentWindow999")
    print(f" • Window Focus Graceful Handshake: {focus_res} (Handled safely)")
    print(" >>> CRITERION 3 PASSED: Native Desktop HAL operational. <<<")

    # -------------------------------------------------------------------------
    # 4. Verify Tool Registry & Engine Integration
    # -------------------------------------------------------------------------
    print("\n[4/4] Testing ToolRegistry Dispatching & Engine Harness Execution...")
    registry = ToolRegistry(workspace_root="workspace")
    schemas = registry.get_schemas()
    print(f" • Registered Tool Schemas: {len(schemas)} tools available")
    tool_names = [s["function"]["name"] for s in schemas]
    print(f"   └─ Tools: {tool_names}")
    assert "bash_execute" in tool_names
    assert "file_write" in tool_names
    assert "file_patch" in tool_names

    # Test file_write dispatch
    res_w = await registry.dispatch("file_write", {
        "file_path": "sandbox_demo.py",
        "content": "def greet(name):\n    return f'Hello, {name}'\n"
    })
    print(f" • Tool 'file_write': Success={res_w.success} | \"{res_w.output}\"")
    assert res_w.success is True

    # Test file_read dispatch
    res_r = await registry.dispatch("file_read", {"file_path": "sandbox_demo.py"})
    print(f" • Tool 'file_read':  Success={res_r.success} | Read {len(res_r.output)} bytes")
    assert "def greet(name)" in res_r.output

    # Test end-to-end Voice Harness Autonomous Interception
    harness = UnifiedAsyncEngine()
    print("\n • Testing Harness Autonomous Execution Intercept for 'run python -c \"print(9*9)\"'...")
    voice_res = await harness.process_voice_turn("run python -c \"print(9*9)\"")
    print(f"   └─ Spoken Response:  \"{voice_res['spoken_response']}\"")
    print(f"   └─ Backend Executed: {voice_res['execution_backend']}")
    assert voice_res["execution_backend"] == "SANDBOX_PTY_EXEC"
    assert "81" in voice_res["spoken_response"]

    # Cleanup demo file and processes
    Path("workspace/sandbox_demo.py").unlink(missing_ok=True)
    registry.close()
    harness.tools.close()

    print("\n" + "=" * 70)
    print(">>> PILLAR 2: THE EXECUTION ENGINE ('THE HANDS') FULLY OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_pillar2())
