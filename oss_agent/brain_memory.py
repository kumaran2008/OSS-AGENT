from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

class BrainMemory:
    """Obsidian-compatible Markdown Vault + SQLite WAL Memory Graph with Entity Disambiguation."""

    def __init__(self, vault_dir: Optional[Path] = None):
        self.vault_dir = vault_dir or (Path.home() / ".oss_agent" / "vault")
        self.notes_dir = self.vault_dir / "notes"
        self.db_path = self.vault_dir / "brain.db"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        with conn:
            # 1. Structured entities & disambiguation rules
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    unique_handle TEXT NOT NULL UNIQUE,
                    metadata_json TEXT DEFAULT '{}',
                    disambiguation_rule TEXT,
                    created_at REAL NOT NULL
                );
            """)
            # 2. Episodic experiences, failures, and learned behaviors
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT DEFAULT '{}',
                    timestamp REAL NOT NULL
                );
            """)
            # 3. FTS5 Index for fast recall
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS brain_fts USING fts5(
                    name,
                    summary,
                    details_json
                );
            """)
        conn.close()

    def resolve_entity(self, alias_name: str) -> Dict[str, Any]:
        """Resolves ambiguity (e.g. multiple 'Kumars'). Returns matched entity or triggers a clarification request."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE LOWER(name) = LOWER(?)", (alias_name.strip(),))
        matches = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if len(matches) == 0:
            return {"status": "NOT_FOUND", "matches": []}
        elif len(matches) == 1:
            return {"status": "RESOLVED", "entity": matches[0]}
        else:
            return {
                "status": "AMBIGUOUS",
                "matches": matches,
                "message": f"Multiple contacts found for '{alias_name}'. Please clarify which one you mean (e.g. Kumar from Work, or Kumar Gym friend)."
            }

    def learn_entity_disambiguation(self, name: str, unique_handle: str, category: str, rule: str, metadata: Dict[str, Any]) -> None:
        """Stores a disambiguation rule so the agent never asks the same clarification question again."""
        conn = sqlite3.connect(str(self.db_path))
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO entities (name, category, unique_handle, metadata_json, disambiguation_rule, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, category, unique_handle, json.dumps(metadata), rule, time.time()))
        conn.close()

        # Write corresponding human-readable Markdown file (Obsidian graph format)
        note_file = self.notes_dir / f"{unique_handle.replace(' ', '_')}.md"
        with open(note_file, "w", encoding="utf-8") as f:
            f.write(f"# Entity: {name}\n\n")
            f.write(f"- **Category**: {category}\n")
            f.write(f"- **Handle**: {unique_handle}\n")
            f.write(f"- **Disambiguation Rule**: {rule}\n")
            f.write(f"- **Attributes**:\n```json\n{json.dumps(metadata, indent=2)}\n```\n")

    def record_experience(self, event_type: str, summary: str, status: str, details: Dict[str, Any]) -> None:
        """Logs successes, user corrections, and failures to avoid repeating mistakes."""
        conn = sqlite3.connect(str(self.db_path))
        with conn:
            conn.execute("""
                INSERT INTO episodic_logs (event_type, summary, status, details_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, summary, status, json.dumps(details), time.time()))
        conn.close()
