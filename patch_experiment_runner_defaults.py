from pathlib import Path
import re

target = Path("agent/pa_scaffolder/experiment_runner.py")
code = target.read_text(encoding="utf-8")

# Replace __init__ definition of SandboxedExperimentRunner
old_init_pattern = r'def __init__\(self, memory[^)]*\):.*?(?=\n    #|\n    def|\Z)'

new_init = """def __init__(
        self,
        memory: Optional[Any] = None,
        verifier: Optional[Any] = None,
        workspace_root: Optional[Union[str, Path]] = None
    ):
        self.workspace_root = Path(workspace_root or ".").resolve()
        
        if memory is None:
            from agent.pa_scaffolder.research_memory import ResearchMemoryLayer
            self.memory = ResearchMemoryLayer(db_path=self.workspace_root / "vault.db")
        else:
            self.memory = memory

        if verifier is None:
            from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier
            self.verifier = MathAndStatsVerifier()
        else:
            self.verifier = verifier

        self.remote_bridge = RemoteComputeBridge(self.workspace_root)"""

code = re.sub(old_init_pattern, new_init, code, count=1, flags=re.DOTALL)
target.write_text(code, encoding="utf-8")

# Validate python compilation
import py_compile
py_compile.compile(str(target), doraise=True)
print("[✓] SandboxedExperimentRunner updated with optional default memory & verifier.")
