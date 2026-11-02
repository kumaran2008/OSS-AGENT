import ast
from pathlib import Path

target = Path("agent/pa_scaffolder/experiment_runner.py")
code = target.read_text(encoding="utf-8")

# Ensure required imports are present
needed_imports = [
    "from typing import Dict, Any, List, Optional, Tuple, Union",
    "from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge, CloudComputeProvider"
]
for imp in needed_imports:
    if imp.split()[1] not in code:
        code = imp + "\n" + code

lines = code.splitlines()
tree = ast.parse("\n".join(lines))

new_init_lines = [
    "    def __init__(",
    "        self,",
    "        memory: Optional[Any] = None,",
    "        verifier: Optional[Any] = None,",
    "        workspace_root: Optional[Union[str, Path]] = None",
    "    ):",
    '        self.workspace_root = Path(workspace_root or ".").resolve()',
    "        if memory is None:",
    "            from agent.pa_scaffolder.research_memory import ResearchMemoryLayer",
    '            self.memory = ResearchMemoryLayer(db_path=self.workspace_root / "vault.db")',
    "        else:",
    "            self.memory = memory",
    "        if verifier is None:",
    "            from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier",
    "            self.verifier = MathAndStatsVerifier()",
    "        else:",
    "            self.verifier = verifier",
    "        self.remote_bridge = RemoteComputeBridge(self.workspace_root)"
]

replaced = False
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "SandboxedExperimentRunner":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                start_idx = item.lineno - 1
                end_idx = item.end_lineno
                lines[start_idx:end_idx] = new_init_lines
                replaced = True
                break
        if replaced:
            break

if not replaced:
    print("[!] Could not locate SandboxedExperimentRunner.__init__ in AST.")
else:
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    import py_compile
    py_compile.compile(str(target), doraise=True)
    print("[✓] AST-replaced SandboxedExperimentRunner.__init__ with default optional arguments.")
