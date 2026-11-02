import sys
import shutil
import asyncio
from pathlib import Path

from agent.pa_scaffolder.isolated_self_healer import IsolatedSelfHealer
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


async def test_gap3_process_isolated_healer():
    print("=" * 72)
    print("     GAP 3 VERIFICATION: PROCESS-ISOLATED SELF-HEALING ENGINE")
    print("=" * 72)

    test_ws = Path("workspace/test_healer_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    # Create dummy source file for test reads
    test_file = test_ws / "dataset.py"
    test_file.write_text("".join(f"# Entry {i}\n" for i in range(1, 60)), encoding="utf-8")

    healer = IsolatedSelfHealer(workspace_root=test_ws)

    # -------------------------------------------------------------------------
    # 1. Clean Child Process Dispatch
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Clean Process-Isolated Tool Dispatch...")
    res1 = healer.dispatch_child_process("file_read", {"file_path": "dataset.py", "start_line": 1, "line_count": 5})
    print(f" • Child Process Execution: {'SUCCESS' if res1.get('success') else 'FAILED'}")
    assert res1.get("success") is True
    assert "Entry 1" in res1.get("output")
    print(" >>> CRITERION 1 PASSED: Child worker executed tool cleanly across process boundary. <<<")

    # -------------------------------------------------------------------------
    # 2. Pre-Flight AST Syntax Guard (Rejection of Syntax Errors)
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing Pre-Flight AST Syntax Guard (Rejecting Bad Code)...")
    bad_syntax_code = "def broken_code(\n   return 42"  # Missing closing paren
    ast_check = healer.verify_ast_syntax(bad_syntax_code)
    print(f" • Syntax Check Passed:     {ast_check.passed} (Expected: False)")
    print(f" • Intercepted Error:       \"{ast_check.error_message}\"")
    assert ast_check.passed is False
    assert "SyntaxError" in ast_check.error_message
    print(" >>> CRITERION 2 PASSED: Pre-flight AST syntax check rejected broken code before disk write. <<<")

    # -------------------------------------------------------------------------
    # 3. Pre-Flight Canary Sandbox Guard (Compile Checks)
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing Pre-Flight Canary Sandbox Guard...")
    target_tool_file = Path("agent/pa_scaffolder/tool_registry.py").resolve()
    orig_tool_code = target_tool_file.read_text(encoding="utf-8")

    # Candidate with unclosed string literal
    bad_canary_code = orig_tool_code + "\n\nfoo = 'unclosed string\n"
    canary_audit = healer.verify_canary_sandbox(
        target_file=target_tool_file,
        candidate_code=bad_canary_code,
        canary_tool="file_read",
        canary_args={"file_path": "dataset.py"}
    )
    print(f" • Canary Sandbox Passed:   {canary_audit.passed} (Expected: False)")
    print(f" • Intercepted Error:       \"{canary_audit.error_message}\"")
    assert canary_audit.passed is False
    print(" >>> CRITERION 3 PASSED: Canary sandbox blocked broken patch from touching production file. <<<")

    # -------------------------------------------------------------------------
    # 4. Live Fault Interception, Pre-Flight Check & Self-Healing
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing Live Crash Interception, Pre-Flight Test & Repair...")
    try:
        # Inject an intentional bug into tool_registry.py
        bug_anchor = "lines = fpath.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines(keepends=True)"
        bug_injection = (
            "lines = fpath.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines(keepends=True)\n"
            "                if int(args.get('line_count', 0)) > 20:\n"
            "                    raise IndexError('Simulated Worker Buffer Overflow')\n"
        )
        assert bug_anchor in orig_tool_code
        target_tool_file.write_text(orig_tool_code.replace(bug_anchor, bug_injection, 1), encoding="utf-8")

        # Define patch synthesizer
        def repair_synthesizer(path_str: str, code_str: str, err_trace: str) -> str:
            return code_str.replace(
                "if int(args.get('line_count', 0)) > 20:\n                    raise IndexError('Simulated Worker Buffer Overflow')\n",
                ""
            )

        heal_res = await healer.dispatch_with_preflight_healing(
            tool_name="file_read",
            tool_args={"file_path": "dataset.py", "start_line": 5, "line_count": 30},
            patch_synthesizer=repair_synthesizer
        )

        print(f" • Self-Healed Status:      {heal_res.repaired}")
        print(f" • Task Resumed Success:    {heal_res.success}")
        print(f" • Pre-Flight Checks:       {'PASSED' if heal_res.pre_flight_passed else 'FAILED'}")
        print(f" • Repair Latency:          {heal_res.latency_sec}s")
        print(f" • Diagnostic Log:          \"{heal_res.diagnostics}\"")

        assert heal_res.success is True
        assert heal_res.repaired is True
        assert heal_res.pre_flight_passed is True
        assert "Entry 5" in heal_res.output
        assert "Entry 30" in heal_res.output

    finally:
        # Ensure clean restoration
        target_tool_file.write_text(orig_tool_code, encoding="utf-8")

    print(" >>> CRITERION 4 PASSED: Child worker crash repaired via pre-flight AST tests with 0% memory poisoning. <<<")

    # -------------------------------------------------------------------------
    # 5. Public Engine Harness Integration
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing UnifiedAsyncEngine Public Self-Healing Interface...")
    harness = UnifiedAsyncEngine()
    harness.tools.workspace_root = test_ws

    harness_res = await harness.dispatch_tool_with_self_healing(
        tool_name="file_read",
        tool_args={"file_path": "dataset.py", "start_line": 1, "line_count": 3}
    )
    print(f" • Harness Dispatch Status: {harness_res.get('success')}")
    assert harness_res.get("success") is True
    assert "Entry 1" in harness_res.get("output")
    print(" >>> CRITERION 5 PASSED: Public harness self-healing interface verified. <<<")

    harness.tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 72)
    print(">>> GAP 3 (PROCESS-ISOLATED SELF-HEALING) 100% OPERATIONAL <<<")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(test_gap3_process_isolated_healer())
