from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_import = "from agent.pa_scaffolder.graph_brain import GraphBrainDB, NodeType"
new_import = """try:
    from agent.pa_scaffolder.graph_brain import GraphBrainDB, NodeType
except ImportError:
    from agent.pa_scaffolder.graph_brain import GraphBrainDB
    from enum import Enum
    class NodeType(str, Enum):
        EPISODIC = "episodic"
        SEMANTIC = "semantic"
        FACT = "fact"
        PERSON = "person"
        CONCEPT = "concept\""""

if old_import in code:
    code = code.replace(old_import, new_import)
    target.write_text(code, encoding="utf-8")
    print("[✓] engine_harness.py import patched safely")
else:
    print("[i] Import already updated or not matching exact string")
