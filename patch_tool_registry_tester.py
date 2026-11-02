from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add import
if "from agent.pa_scaffolder.rooms_engine import TesterAutonomousAuditor" not in code:
    code = "from agent.pa_scaffolder.rooms_engine import TesterAutonomousAuditor\n" + code

# 2. Add tester to __init__
old_init = "self.orchestrator = WorkspaceOrchestrator(self.workspace_root)"
new_init = old_init + "\n        self.tester = TesterAutonomousAuditor(self.workspace_root)"

if old_init in code and "self.tester =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add dispatch handlers
old_dispatch = '            # -----------------------------------------------------------------\n            # Workspace Surface & Health Probing Tools'
new_dispatch = """            # -----------------------------------------------------------------
            # Tester Room Specialized QA Tools
            # -----------------------------------------------------------------
            if tool_name == "tester_run_suite":
                cmd = args.get("command")
                res = await self.tester.execute_audit(self.pty, test_command=cmd)
                return ToolResult(tool_name=tool_name, success=(res.failed == 0), output=res.report)

            elif tool_name == "tester_generate_adversarial_suite":
                mod = args.get("module_name", "")
                fn = args.get("function_name", "")
                spec = args.get("args_spec", ["x"])
                test_code = self.tester.generate_adversarial_suite(mod, fn, spec)
                target_f = f"tests/test_adversarial_{fn}.py"
                # Write to tests/ (permitted in tester mode)
                full_p = self.workspace_root / target_f
                full_p.parent.mkdir(parents=True, exist_ok=True)
                full_p.write_text(test_code, encoding="utf-8")
                return ToolResult(tool_name=tool_name, success=True, output=f"Generated adversarial suite at {target_f}")

"""

if "tester_run_suite" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch + old_dispatch)

# 4. Add schemas to get_all_tool_schemas
old_schema = '            {"type": "function", "function": {"name": "workspace_open_editor",'
new_schema = """            {"type": "function", "function": {"name": "tester_run_suite", "description": "Runs project test suite with framework auto-detection and flakiness verification", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "tester_generate_adversarial_suite", "description": "Generates edge-case, boundary, and fuzz test harness for a function", "parameters": {"type": "object", "properties": {"module_name": {"type": "string"}, "function_name": {"type": "string"}, "args_spec": {"type": "array", "items": {"type": "string"}}}, "required": ["module_name", "function_name"]}}},
"""

if "tester_run_suite" not in code and old_schema in code:
    code = code.replace(old_schema, new_schema + old_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered tester_run_suite and tester_generate_adversarial_suite in tool_registry.py")
