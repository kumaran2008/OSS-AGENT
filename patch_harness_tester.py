from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

tester_handler = """    async def handle_conversational_tester_task(self, raw_text: str) -> Dict[str, Any]:
        \"\"\"
        Wires natural user test requests directly to TesterAutonomousAuditor:
        1. Auto-detects test framework.
        2. Executes PTY test suite with flakiness checking.
        3. Synthesizes spoken summary.
        \"\"\"
        audit_res = await self.rooms.execute_tester_audit(self.tools.pty)
        summary = (
            f"Audit complete. Ran {audit_res.total_run} tests: {audit_res.passed} passed, "
            f"{audit_res.failed} failed, {audit_res.flaky} flaky. Latency {audit_res.duration_sec:.1f}s."
        )
        await self.voice_controller.synthesize_and_dispatch_async(summary, is_system_command=False)
        return {
            "type": "TEST_AUDIT_COMPLETE",
            "framework": audit_res.framework_detected,
            "passed": audit_res.passed,
            "failed": audit_res.failed,
            "flaky": audit_res.flaky,
            "report": audit_res.report,
            "spoken_response": summary,
            "execution_backend": "TESTER_ROOM"
        }
"""

if "def handle_conversational_tester_task" not in code:
    code = code.replace("class UnifiedAsyncEngine:", "class UnifiedAsyncEngine:\n" + tester_handler)

conversational_tester_hook = """        # -------------------------------------------------------------
        # TESTER MODE CONVERSATIONAL TASK INTERCEPTOR
        # -------------------------------------------------------------
        if self.rooms.current_mode == AgentMode.TESTER:
            test_keywords = ["test", "audit", "run", "check", "regression", "flaky", "verify"]
            if any(k in raw_text.lower() for k in test_keywords) and not switched:
                return await self.handle_conversational_tester_task(raw_text)
"""

if "TESTER MODE CONVERSATIONAL TASK INTERCEPTOR" not in code:
    anchor = "        # -------------------------------------------------------------\n        # BUILDER MODE CONVERSATIONAL TASK INTERCEPTOR"
    code = code.replace(anchor, conversational_tester_hook + "\n" + anchor)

target.write_text(code, encoding="utf-8")
print("[✓] Wired conversational tester handler into engine_harness.py")
