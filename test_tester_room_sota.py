import asyncio
import subprocess
import shutil
from pathlib import Path

from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode, TesterAutonomousAuditor
from agent.pa_scaffolder.pty_sandbox import InteractiveSandboxSession
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_tester_room_sota():
    print("=" * 70)
    print("     TESTER ROOM SOTA SPECIFICATIONS & QA AUDIT BENCHMARK")
    print("=" * 70)

    test_ws = Path("workspace/test_qa_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. Verify Mode Transition & Read-Only Invariant Guard
    # -------------------------------------------------------------------------
    print("\n[1/6] Testing Read-Only Invariant Enforcement...")
    auditor = TesterAutonomousAuditor(test_ws)

    # Attempt 1: Try modifying production file (MUST BE BLOCKED)
    ok_prod, err_prod = auditor.is_modification_allowed("core/database.py")
    print(f" • Modification of 'core/database.py': {'ALLOWED' if ok_prod else 'BLOCKED (Correct)'}")
    assert ok_prod is False
    assert "Direct modification of production source" in err_prod

    # Attempt 2: Try writing to tests directory (MUST BE ALLOWED)
    ok_test, _ = auditor.is_modification_allowed("tests/test_auth.py")
    print(f" • Modification of 'tests/test_auth.py': {'ALLOWED (Correct)' if ok_test else 'BLOCKED'}")
    assert ok_test is True
    print(" >>> CRITERION 1 PASSED: Read-only guard protects production sources. <<<")

    # -------------------------------------------------------------------------
    # 2. Test Framework Auto-Discovery
    # -------------------------------------------------------------------------
    print("\n[2/6] Testing Framework Auto-Discovery...")
    (test_ws / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    fw_name, cmd = auditor.detect_framework()
    print(f" • Discovered Framework:  {fw_name} (Command: '{cmd}')")
    assert fw_name == "pytest"
    print(" >>> CRITERION 2 PASSED: Test framework detected accurately. <<<")

    # -------------------------------------------------------------------------
    # 3. Adversarial Edge-Case Suite Generation & Execution
    # -------------------------------------------------------------------------
    print("\n[3/6] Testing Adversarial Edge-Case Suite Generation...")
    # Create sample module with a division guard
    (test_ws / "calc_service.py").write_text(
        "def safe_divide(x, y):\n"
        "    if x is None or y is None: raise TypeError('None not allowed')\n"
        "    if y == 0: return 0.0\n"
        "    return x / y\n",
        encoding="utf-8"
    )

    adv_code = auditor.generate_adversarial_suite("calc_service", "safe_divide", ["x", "y"])
    adv_file = test_ws / "test_adversarial.py"
    adv_file.write_text(adv_code, encoding="utf-8")

    pty = InteractiveSandboxSession(workspace_root=str(test_ws))
    code, out = pty.execute_command("python test_adversarial.py")
    print(f" • Adversarial Output:\n   {out.strip()}")
    assert code == 0
    assert "ALL_BOUNDARY_GUARDS_PASSED" in out
    print(" >>> CRITERION 3 PASSED: Adversarial fuzz suite validated boundary inputs. <<<")

    # -------------------------------------------------------------------------
    # 4. Flakiness & Regression Audit Loop
    # -------------------------------------------------------------------------
    print("\n[4/6] Testing Regression Audit & Flakiness Filter...")
    # Write a test file with 2 passing tests and 1 failing test
    (test_ws / "test_sample.py").write_text(
        "import unittest\n"
        "class TestSuite(unittest.TestCase):\n"
        "    def test_alpha(self): self.assertTrue(True)\n"
        "    def test_beta(self): self.assertEqual(1+1, 2)\n"
        "    def test_gamma(self): self.assertEqual(10, 20) # Intentional regression\n",
        encoding="utf-8"
    )

    audit_res = await auditor.execute_audit(pty, test_command="python -m unittest test_sample.py")
    print(f" • Total Tests Run:       {audit_res.total_run}")
    print(f" • Tests Passed:          {audit_res.passed}")
    print(f" • Tests Failed:          {audit_res.failed}")
    print(f" • Execution Duration:    {audit_res.duration_sec:.2f}s")
    assert audit_res.failed >= 1
    assert "DETECTED REGRESSIONS" in audit_res.report
    print(" >>> CRITERION 4 PASSED: Deterministic regression isolated and reported. <<<")

    # -------------------------------------------------------------------------
    # 5. Tool Registry Integration
    # -------------------------------------------------------------------------
    print("\n[5/6] Testing Tool Registry QA Tool Dispatch...")
    tools = ToolRegistry(workspace_root=str(test_ws))

    res_adv = await tools.dispatch("tester_generate_adversarial_suite", {
        "module_name": "calc_service",
        "function_name": "safe_divide",
        "args_spec": ["a", "b"]
    })
    print(f" • Generated Tool File:   \"{res_adv.output}\"")
    assert res_adv.success is True
    assert (test_ws / "tests/test_adversarial_safe_divide.py").exists()
    print(" >>> CRITERION 5 PASSED: ToolRegistry dispatched adversarial test generator. <<<")

    # -------------------------------------------------------------------------
    # 6. Conversational End-to-End Turn in Tester Mode
    # -------------------------------------------------------------------------
    print("\n[6/6] Testing Conversational Turn in TESTER Mode...")
    harness = UnifiedAsyncEngine()
    harness.tools.workspace_root = test_ws
    harness.tools.pty.workspace_root = test_ws
    harness.rooms.workspace = test_ws
    harness.rooms.tester_auditor.workspace = test_ws

    # Switch to Tester mode
    res_mode = await harness.process_voice_turn("switch to tester mode")
    print(f" • Mode Switch:           \"{res_mode['spoken_response']}\"")
    assert harness.rooms.current_mode == AgentMode.TESTER

    # Run conversational test command
    res_turn = await harness.process_voice_turn("run tests and audit regressions")
    print(f" • Turn Type:             {res_turn.get('type')}")
    print(f" • Spoken Response:       \"{res_turn.get('spoken_response')}\"")
    assert res_turn.get("type") == "TEST_AUDIT_COMPLETE"
    assert "Audit complete" in res_turn.get("spoken_response")
    print(" >>> CRITERION 6 PASSED: Conversational audit executed end-to-end. <<<")

    # Teardown
    pty.close()
    tools.close()
    harness.tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> TESTER ROOM FULLY CONFIGURED & VERIFIED PRODUCTION READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_tester_room_sota())
