from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add Phase 3 imports
imports = """from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier, StatisticalAuditReport
from agent.pa_scaffolder.experiment_runner import SandboxedExperimentRunner, SweepRunResult
"""
if "from agent.pa_scaffolder.math_verifier import" not in code:
    code = imports + code

# 2. Add verifier and experiment runner to RoomsEngine.__init__
old_init = "self.literature_engine = LiteratureEngine(self.research_memory)"
new_init = old_init + """
        self.math_verifier = MathAndStatsVerifier()
        self.experiment_runner = SandboxedExperimentRunner(self.workspace, self.research_memory, self.math_verifier)"""

if old_init in code and "self.math_verifier =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add public orchestration methods to RoomsEngine
methods = """
    async def run_experiment_sweep(
        self,
        script_rel_path: str,
        metric_key: str,
        seeds: Optional[List[int]] = None,
        baseline_target: Optional[float] = None,
        paper_id: Optional[str] = None,
        name: str = "Paper Code Reproduction"
    ) -> Dict[str, Any]:
        \"\"\"Runs multi-seed sandboxed experiment with statistical sanity verification.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        sweep_res = await self.experiment_runner.execute_multi_seed_sweep(
            script_relative_path=script_rel_path,
            metric_key=metric_key,
            seeds=seeds,
            baseline_target=baseline_target,
            paper_id=paper_id,
            name=name
        )
        return asdict(sweep_res)

    def verify_mathematical_derivation(self, expr_a: str, expr_b: str, variables: Optional[List[str]] = None) -> Tuple[bool, str]:
        \"\"\"Verifies symbolic and numeric equivalence of mathematical formulations.\"\"\"
        self.current_mode = AgentMode.RESEARCHER
        return self.math_verifier.verify_symbolic_equivalence(expr_a, expr_b, variables)
"""

if "def run_experiment_sweep" not in code:
    code = code + "\n" + methods

target.write_text(code, encoding="utf-8")
print("[✓] Integrated MathVerifier and SandboxedExperimentRunner into rooms_engine.py")
