from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add imports
phase3_imports = """from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier
from agent.pa_scaffolder.experiment_runner import SandboxedExperimentRunner
"""
if "from agent.pa_scaffolder.math_verifier import" not in code:
    code = phase3_imports + code

# 2. Add instances to ToolRegistry.__init__
old_init = "self.literature = LiteratureEngine(self.research_memory)"
new_init = old_init + """
        self.math_verifier = MathAndStatsVerifier()
        self.experiment_runner = SandboxedExperimentRunner(self.workspace_root, self.research_memory, self.math_verifier)"""

if old_init in code and "self.math_verifier =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add dispatch handlers
old_dispatch = '            # -----------------------------------------------------------------\n            # Literature & Academic Research Tools'
new_dispatch = """            # -----------------------------------------------------------------
            # Math, Statistics & Sandboxed Experiment Tools
            # -----------------------------------------------------------------
            if tool_name == "math_verify_derivation":
                ea = args.get("expr_a", "")
                eb = args.get("expr_b", "")
                vars_spec = args.get("variables", ["x", "y"])
                ok, msg = self.math_verifier.verify_symbolic_equivalence(ea, eb, vars_spec)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

            elif tool_name == "stats_audit_significance":
                values = args.get("values", [])
                base = args.get("baseline")
                audit = self.math_verifier.audit_reproduced_metrics(values, base)
                return ToolResult(tool_name=tool_name, success=True, output=audit.verdict)

            elif tool_name == "experiment_run_sweep":
                script = args.get("script_path", "")
                m_key = args.get("metric_key", "")
                base = args.get("baseline")
                seeds = args.get("seeds", [42, 1337, 2026])
                sweep = await self.experiment_runner.execute_multi_seed_sweep(
                    script_relative_path=script,
                    metric_key=m_key,
                    seeds=seeds,
                    baseline_target=base
                )
                return ToolResult(tool_name=tool_name, success=("REPRODUCED" in sweep.report_md), output=sweep.report_md)

"""

if "math_verify_derivation" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch + old_dispatch)

# 4. Add schemas to get_all_tool_schemas
old_schema = '            {"type": "function", "function": {"name": "literature_search",'
new_schemas = """            {"type": "function", "function": {"name": "math_verify_derivation", "description": "Verifies symbolic or numeric equivalence of mathematical expressions", "parameters": {"type": "object", "properties": {"expr_a": {"type": "string"}, "expr_b": {"type": "string"}}, "required": ["expr_a", "expr_b"]}}},
            {"type": "function", "function": {"name": "stats_audit_significance", "description": "Runs Welch t-test, variance check, and p-hacking audit on metrics", "parameters": {"type": "object", "properties": {"values": {"type": "array", "items": {"type": "number"}}, "baseline": {"type": "number"}}, "required": ["values"]}}},
            {"type": "function", "function": {"name": "experiment_run_sweep", "description": "Executes sandboxed multi-seed sweep of paper code with auto-dependency healing", "parameters": {"type": "object", "properties": {"script_path": {"type": "string"}, "metric_key": {"type": "string"}, "baseline": {"type": "number"}}, "required": ["script_path", "metric_key"]}}},
"""

if "math_verify_derivation" not in code and old_schema in code:
    code = code.replace(old_schema, new_schemas + old_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered Phase 3 tools in tool_registry.py")
