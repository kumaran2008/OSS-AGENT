import re
from pathlib import Path

target = Path("agent/pa_scaffolder/graph_brain.py")
content = target.read_text(encoding="utf-8")

# 1. Inject imports if missing
if "from contextlib import contextmanager" not in content:
    content = "from contextlib import contextmanager\n" + content
if "from enum import Enum" not in content and "import Enum" not in content:
    content = "from enum import Enum\n" + content
if "import sqlite3" not in content:
    content = "import sqlite3\n" + content

# 2. Add NodeType Enum if missing
if "class NodeType" not in content:
    node_type_code = """

class NodeType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    FACT = "fact"
    PERSON = "person"
    CONCEPT = "concept"
"""
    content += node_type_code

# 3. Add _get_conn method to GraphBrainDB if missing
if "def _get_conn" not in content:
    conn_helper = """
    @contextmanager
    def _get_conn(self):
        if hasattr(self, "conn") and self.conn is not None:
            yield self.conn
        elif hasattr(self, "db_path"):
            c = sqlite3.connect(str(self.db_path))
            try:
                yield c
            finally:
                c.close()
        else:
            c = sqlite3.connect("workspace/graph_brain.db")
            try:
                yield c
            finally:
                c.close()
"""
    match = re.search(r"(class GraphBrainDB[^\:]*:\n)", content)
    if match:
        idx = match.end()
        content = content[:idx] + conn_helper + content[idx:]
    else:
        content += "\n" + conn_helper

target.write_text(content, encoding="utf-8")
print("[✓] Successfully injected NodeType and _get_conn into graph_brain.py")
