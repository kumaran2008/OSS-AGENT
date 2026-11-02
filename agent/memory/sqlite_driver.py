import os
import sqlite3
from pathlib import Path
from typing import Optional


class SQLiteMemoryDriver:
    """
    High-throughput SQLite3 storage engine configured for WAL mode,
    memory-mapped I/O, and low-latency concurrent retrieval.
    """

    DEFAULT_DB_PATH = Path("workspace/memory/graph_brain_v2.db")
    SCHEMA_PATH = Path(__file__).parent / "schema.sql"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def get_connection(self) -> sqlite3.Connection:
        """Yields an optimized SQLite connection with aggressive caching."""
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=15.0
        )
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA mmap_size = 268435456;")       # 256MB memory map
        conn.execute("PRAGMA cache_size = -64000;")          # 64MB cache
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn

    def _init_database(self) -> None:
        """Applies schema DDL if tables do not exist."""
        if not self.SCHEMA_PATH.exists():
            raise FileNotFoundError(f"Schema DDL not found at {self.SCHEMA_PATH}")

        schema_sql = self.SCHEMA_PATH.read_text(encoding="utf-8")
        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            conn.commit()
