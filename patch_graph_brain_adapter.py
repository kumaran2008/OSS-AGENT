from pathlib import Path

target = Path("agent/pa_scaffolder/graph_brain.py")
code = target.read_text(encoding="utf-8")

adapter_code = """

# =====================================================================
# SYSTEM COMPATIBILITY ADAPTER (Guaranteed Schema & Context Binding)
# =====================================================================
from contextlib import contextmanager
from enum import Enum
import inspect
import sqlite3

class NodeType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    FACT = "fact"
    PERSON = "person"
    CONCEPT = "concept"

@contextmanager
def _runtime_get_conn(self):
    if hasattr(self, "conn") and self.conn is not None:
        yield self.conn
    elif hasattr(self, "db_path") and self.db_path:
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()
    else:
        conn = sqlite3.connect("workspace/graph_brain.db")
        try:
            yield conn
        finally:
            conn.close()

GraphBrainDB._get_conn = _runtime_get_conn

if hasattr(GraphBrainDB, "add_or_update_node"):
    _orig_add_node = GraphBrainDB.add_or_update_node

    def _adapted_add_or_update_node(self, *args, **kwargs):
        sig = inspect.signature(_orig_add_node)
        params = sig.parameters

        # Translate node_id keyword to whatever parameter the method expects
        if "node_id" in kwargs and "node_id" not in params:
            val = kwargs.pop("node_id")
            if "name" in params:
                kwargs["name"] = val
            elif "id" in params:
                kwargs["id"] = val
            elif "node_name" in params:
                kwargs["node_name"] = val
            else:
                args = (val,) + args

        # Normalize Enum to raw string
        if "node_type" in kwargs:
            nt = kwargs["node_type"]
            kwargs["node_type"] = nt.value if hasattr(nt, "value") else str(nt)

        # Translate metadata <-> properties
        if "metadata" in kwargs and "metadata" not in params:
            if "properties" in params:
                kwargs["properties"] = kwargs.pop("metadata")
            elif "data" in params:
                kwargs["data"] = kwargs.pop("metadata")

        return _orig_add_node(self, *args, **kwargs)

    GraphBrainDB.add_or_update_node = _adapted_add_or_update_node
"""

if "_runtime_get_conn" not in code:
    code += "\n" + adapter_code
    target.write_text(code, encoding="utf-8")
    print("[✓] Successfully attached universal adapter to GraphBrainDB")
else:
    print("[i] Adapter already present in graph_brain.py")
