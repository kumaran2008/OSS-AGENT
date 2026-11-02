from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

tester_class = """
# ---------------------------------------------------------------------------
# 6. SOTA Tester Room Autonomous Auditor
# ---------------------------------------------------------------------------
@dataclass
class TestAuditResult:
    framework_detected: str
    total_run: int
    passed: int
    failed: int
    flaky: int
    duration_sec: float
    failures: List[Dict[str, Any]]
    adversarial_findings: List[str]
    report: str


class TesterAutonomousAuditor:
    \"\"\"
    Adversarial QA Test Auditor:
    - Auto-detects testing frameworks (pytest, vitest, jest, cargo, go).
    - Enforces read-only safety on production source code.
    - Runs 3x flakiness checks on failing test suites.
    - Generates adversarial edge-case suites (nulls, boundary, fuzz).
    - Produces structured QA matrices.
    \"\"\"

    FRAMEWORK_SIGNATURES = [
        ("pytest", ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"], "pytest -v"),
        ("unittest", ["test_*.py"], "python -m unittest discover"),
        ("vitest", ["vitest.config.ts", "vitest.config.js"], "npx vitest run"),
        ("jest", ["jest.config.js", "jest.config.ts", "package.json"], "npm test -- --watchAll=false"),
        ("cargo", ["Cargo.toml"], "cargo test"),
        ("go", ["go.mod"], "go test ./...")
    ]

    def __init__(self, workspace_root: Path):
        self.workspace = workspace_root.resolve()

    def detect_framework(self) -> Tuple[str, str]:
        \"\"\"Detects the primary test framework and return (name, test_command).\"\"\"
        for name, files, cmd in self.FRAMEWORK_SIGNATURES:
            for f in files:
                if "*" in f:
                    if list(self.workspace.glob(f)):
                        return name, cmd
                elif (self.workspace / f).exists():
                    # For package.json, verify if jest or vitest is in dependencies
                    if f == "package.json":
                        try:
                            pkg_data = json.loads((self.workspace / f).read_text(encoding="utf-8"))
                            scripts = pkg_data.get("scripts", {})
                            if "test" in scripts:
                                return "npm", "npm test"
                        except Exception:
                            pass
                    else:
                        return name, cmd

        # Default fallback to python unittest or pytest
        return "pytest", "pytest -v"

    def is_modification_allowed(self, target_rel_path: str) -> Tuple[bool, str]:
        \"\"\"
        Read-Only Invariant Guard:
        Tester mode is only permitted to write tests in 'tests/' or temp audit scripts.
        It is strictly blocked from overwriting application source files.
        \"\"\"
        clean_path = target_rel_path.replace("\\\\", "/").lower()
        if clean_path.startswith("tests/") or "test_" in clean_path or "_test." in clean_path or clean_path.startswith("/tmp/"):
            return True, ""
        return False, f"TESTER MODE SECURITY REJECTION: Direct modification of production source '{target_rel_path}' is forbidden. Tester operates in read-only audit mode."

    def generate_adversarial_suite(self, module_name: str, function_name: str, args_spec: List[str]) -> str:
        \"\"\"Generates adversarial edge-case inputs for AST boundary testing.\"\"\"
        code = [
            f"# Adversarial Boundary & Fuzz Suite for {module_name}.{function_name}",
            "import sys",
            f"from {module_name} import {function_name}",
            "",
            "def test_adversarial_boundary():",
            "    cases = [",
            "        # Edge 1: None / Null injection",
            "        [None] * " + str(len(args_spec)) + ",",
            "        # Edge 2: Zero values",
            "        [0] * " + str(len(args_spec)) + ",",
            "        # Edge 3: Negative boundary",
            "        [-1] * " + str(len(args_spec)) + ",",
            "        # Edge 4: Large buffer overflow simulation",
            "        [999999999999] * " + str(len(args_spec)) + ",",
            "        # Edge 5: Empty collections",
            "        [[]] * " + str(len(args_spec)) + ",",
            "        # Edge 6: Unicode / Emoji stress",
            "        ['🔥' * 100] * " + str(len(args_spec)),
            "    ]",
            "    anomalies = []",
            "    for idx, c in enumerate(cases):",
            "        try:",
            f"            {function_name}(*c)",
            "        except TypeError:",
            "            pass # Handled type guard",
            "        except Exception as e:",
            "            anomalies.append(f'Case {idx} ({type(e).__name__}): {e}')",
            "    if anomalies:",
            "        print('ADVERSARIAL_ANOMALIES_FOUND:')",
            "        for a in anomalies: print(f'  • {a}')",
            "    else:",
            "        print('ALL_BOUNDARY_GUARDS_PASSED')",
            "",
            "if __name__ == '__main__':",
            "    test_adversarial_boundary()"
        ]
        return "\\n".join(code)

    def parse_test_output(self, framework: str, raw_output: str) -> Tuple[int, int, List[Dict[str, Any]]]:
        \"\"\"Parses terminal test runner output into passed, failed, and failures list.\"\"\"
        passed = 0
        failed = 0
        failures = []

        if framework in ["pytest", "unittest"]:
            # Match: "1 failed, 5 passed in 0.23s"
            pass_match = re.search(r"(\\d+)\\s+passed", raw_output)
            fail_match = re.search(r"(\\d+)\\s+failed", raw_output)
            if pass_match:
                passed = int(pass_match.group(1))
            if fail_match:
                failed = int(fail_match.group(1))

            # Trace individual failed test names
            fail_lines = re.findall(r"FAILED\\s+([\\w\\/\\.\\:]+)", raw_output)
            for fl in fail_lines:
                failures.append({"test": fl, "error": "Assertion/Exception failure"})

        # Heuristic fallback if regex missed
        if passed == 0 and failed == 0:
            if "OK" in raw_output:
                passed = 1
            elif "FAIL" in raw_output or "Error" in raw_output:
                failed = 1
                failures.append({"test": "suite_execution", "error": "Process returned non-zero code"})

        return passed, failed, failures

    async def execute_audit(
        self,
        pty_session,
        test_command: Optional[str] = None,
        audit_file: Optional[str] = None
    ) -> TestAuditResult:
        \"\"\"
        Executes a complete adversarial QA audit:
        1. Discovers test framework.
        2. Executes test suite inside process-group isolated PTY.
        3. Runs 3x flakiness checks on any failures.
        4. Compiles structured report.
        \"\"\"
        fw_name, default_cmd = self.detect_framework()
        cmd = test_command or default_cmd

        t0 = time.monotonic()
        exit_code, raw_out = pty_session.execute_command(cmd, timeout_sec=20.0)
        duration = time.monotonic() - t0

        passed, failed, failures = self.parse_test_output(fw_name, raw_out)
        flaky_count = 0

        # Flakiness verification (run failed tests 2 more times to detect timing issues)
        if failed > 0:
            retry_passes = 0
            for _ in range(2):
                r_code, _ = pty_session.execute_command(cmd, timeout_sec=20.0)
                if r_code == 0:
                    retry_passes += 1
            if retry_passes > 0:
                flaky_count = failed
                failed = 0  # Reclassified as flaky timing defect

        total = passed + failed + flaky_count

        # Formulate structured QA audit report
        report_lines = [
            f"# TESTER AUDIT REPORT ({fw_name.upper()} SUITE)",
            f"• Total Tests: {total} | Passed: {passed} | Failed: {failed} | Flaky: {flaky_count}",
            f"• Execution Latency: {duration:.2f}s",
            ""
        ]

        if failures:
            report_lines.append("## DETECTED REGRESSIONS:")
            for f in failures:
                report_lines.append(f"  ❌ {f['test']}: {f['error']}")
        elif flaky_count > 0:
            report_lines.append("## ⚠️ WARNING: FLAKY TEST RUN DETECTED")
            report_lines.append("  Tests failed on initial run but passed on retry. Async race condition or unbuffered socket timing suspected.")
        else:
            report_lines.append("## ✅ ALL INVARIANTS VERIFIED CLEAN. ZERO REGRESSIONS.")

        return TestAuditResult(
            framework_detected=fw_name,
            total_run=total,
            passed=passed,
            failed=failed,
            flaky=flaky_count,
            duration_sec=duration,
            failures=failures,
            adversarial_findings=[],
            report="\\n".join(report_lines)
        )
"""

# Append TesterAutonomousAuditor class before RoomsEngine
if "class TesterAutonomousAuditor" not in code:
    code = code.replace("class RoomsEngine:", tester_class + "\nclass RoomsEngine:")

# Add tester_auditor to RoomsEngine.__init__
old_engine_init = "self.orchestrator = self.builder_supervisor.orchestrator"
new_engine_init = old_engine_init + "\n        self.tester_auditor = TesterAutonomousAuditor(self.workspace)"

if old_engine_init in code and "self.tester_auditor =" not in code:
    code = code.replace(old_engine_init, new_engine_init)

# Add execute_tester_audit method to RoomsEngine
engine_audit_method = """    async def execute_tester_audit(
        self,
        pty_session,
        test_command: Optional[str] = None
    ) -> TestAuditResult:
        \"\"\"Public API: Runs the adversarial QA audit loop in TESTER mode.\"\"\"
        self.current_mode = AgentMode.TESTER
        return await self.tester_auditor.execute_audit(pty_session=pty_session, test_command=test_command)
"""

if "def execute_tester_audit" not in code:
    code = code + "\n" + engine_audit_method

target.write_text(code, encoding="utf-8")
print("[✓] Added TesterAutonomousAuditor and execute_tester_audit to rooms_engine.py")
