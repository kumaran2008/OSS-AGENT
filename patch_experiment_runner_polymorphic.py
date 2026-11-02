import ast
from pathlib import Path

target = Path("agent/pa_scaffolder/experiment_runner.py")
code = target.read_text(encoding="utf-8")

# Ensure typing and imports are present
if "from typing import" in code:
    if "Union" not in code:
        code = code.replace("from typing import ", "from typing import Union, ")
    if "Optional" not in code:
        code = code.replace("from typing import ", "from typing import Optional, ")
    if "Any" not in code:
        code = code.replace("from typing import ", "from typing import Any, ")

lines = code.splitlines()
tree = ast.parse("\n".join(lines))

new_init_lines = [
    "    def __init__(",
    "        self,",
    "        arg1: Any = None,",
    "        arg2: Any = None,",
    "        arg3: Any = None,",
    "        *,",
    "        memory: Optional[Any] = None,",
    "        verifier: Optional[Any] = None,",
    "        workspace_root: Optional[Union[str, Path]] = None",
    "    ):",
    "        resolved_ws = workspace_root",
    "        resolved_mem = memory",
    "        resolved_ver = verifier",
    "        ",
    "        positionals = [a for a in (arg1, arg2, arg3) if a is not None]",
    "        for item in positionals:",
    "            if isinstance(item, (str, Path)) and resolved_ws is None:",
    "                resolved_ws = item",
    '            elif hasattr(item, "store_paper") or hasattr(item, "record_dead_end") or "Memory" in type(item).__name__:',
    "                if resolved_mem is None:",
    "                    resolved_mem = item",
    '            elif hasattr(item, "verify_mathematical_derivation") or hasattr(item, "audit_experimental_seeds") or "Verifier" in type(item).__name__:',
    "                if resolved_ver is None:",
    "                    resolved_ver = item",
    "            elif resolved_ws is None and not hasattr(item, \"store_paper\") and not hasattr(item, \"verify_mathematical_derivation\"):",
    "                resolved_ws = item",
    "        ",
    '        self.workspace_root = Path(resolved_ws or ".").resolve()',
    "        if resolved_mem is None:",
    "            from agent.pa_scaffolder.research_memory import ResearchMemoryLayer",
    '            self.memory = ResearchMemoryLayer(db_path=self.workspace_root / "vault.db")',
    "        else:",
    "            self.memory = resolved_mem",
    "        ",
    "        if resolved_ver is None:",
    "            from agent.pa_scaffolder.math_verifier import MathAndStatsVerifier",
    "            self.verifier = MathAndStatsVerifier()",
    "        else:",
    "            self.verifier = resolved_ver",
    "        ",
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

if replaced:
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    import py_compile
    py_compile.compile(str(target), doraise=True)
    print("[✓] SandboxedExperimentRunner polymorphic __init__ successfully installed.")
else:
    print("[!] Could not locate SandboxedExperimentRunner.__init__.")
