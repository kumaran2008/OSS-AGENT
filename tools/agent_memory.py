import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = WORKSPACE_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

class UserProfileMemory:
    """
    Tracks persistent user traits, coding habits, and preferred styles across sessions.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.path = storage_path or (DATA_DIR / "user_profile.json")
        self.profile = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "user_name": "Developer",
            "preferred_languages": ["python"],
            "preferred_style": "minimal, modular, well-tested",
            "target_device": "mobile_termux",
            "custom_instructions": [],
            "interaction_count": 0
        }

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.profile, f, indent=2)
        except Exception:
            pass

    def update_preference(self, key: str, value: Any) -> None:
        self.profile[key] = value
        self.save()

    def add_instruction(self, instruction: str) -> None:
        if instruction not in self.profile["custom_instructions"]:
            self.profile["custom_instructions"].append(instruction)
            self.save()

    def get_system_prompt_context(self) -> str:
        instructions = "; ".join(self.profile.get("custom_instructions", [])) or "None specified"
        return (
            f"\n[User Memory Context]\n"
            f"- User Name/Handle: {self.profile.get('user_name')}\n"
            f"- Preferred Languages: {', '.join(self.profile.get('preferred_languages', []))}\n"
            f"- Preferred Code Style: {self.profile.get('preferred_style')}\n"
            f"- Device Constraints: {self.profile.get('target_device')}\n"
            f"- Custom User Directives: {instructions}\n"
        )


class ConversationMemory:
    """
    Stores full chat history and uses SQLite FTS5 for recalling past discussions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (DATA_DIR / "conversation_history.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    content TEXT,
                    timestamp REAL
                )
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    content='messages',
                    content_rowid='id'
                )
            """)
            conn.commit()

    def log_message(self, role: str, content: str) -> None:
        """Saves a single conversation turn (user or assistant)."""
        if not content.strip():
            return
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (role, content, timestamp) VALUES (?, ?, ?)",
                (role, content, time.time())
            )
            row_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO messages_fts (rowid, content) VALUES (?, ?)",
                (row_id, content)
            )
            conn.commit()

    def get_recent_history(self, limit: int = 6) -> List[Dict[str, str]]:
        """Returns the most recent N turns for active context."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def search_past_topics(self, query: str, limit: int = 3) -> List[str]:
        """Recalls relevant past user conversations based on keywords."""
        clean_words = re.findall(r"\b[A-Za-z0-9_]{3,}\b", query)
        if not clean_words:
            return []
        fts_query = " OR ".join(clean_words[:8])

        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT m.role, m.content
                    FROM messages_fts f
                    JOIN messages m ON f.rowid = m.id
                    WHERE messages_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit))
                for row in cursor.fetchall():
                    results.append(f"{row[0].capitalize()}: {row[1]}")
        except Exception:
            pass
        return results


class EpisodicExecutionMemory:
    """
    Stores code execution error traces and corresponding successful patches.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (DATA_DIR / "episodic_memory.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_name TEXT,
                    error_signature TEXT,
                    resolution_patch TEXT,
                    explanation TEXT,
                    timestamp REAL
                )
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                    error_signature,
                    explanation,
                    content='episodes',
                    content_rowid='id'
                )
            """)
            conn.commit()

    def record_resolution(self, repo_name: str, error_signature: str, resolution_patch: str, explanation: str) -> None:
        if not error_signature.strip():
            return
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO episodes (repo_name, error_signature, resolution_patch, explanation, timestamp) VALUES (?, ?, ?, ?, ?)",
                (repo_name, error_signature, resolution_patch, explanation, time.time())
            )
            row_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO episodes_fts (rowid, error_signature, explanation) VALUES (?, ?, ?)",
                (row_id, error_signature, explanation)
            )
            conn.commit()

    def recall_similar_fix(self, current_error: str, limit: int = 2) -> List[Dict[str, Any]]:
        if not current_error.strip():
            return []

        clean_words = re.findall(r"\b[A-Za-z0-9_]{3,}\b", current_error)
        if not clean_words:
            return []
        fts_query = " OR ".join(clean_words[:12])

        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT e.repo_name, e.error_signature, e.resolution_patch, e.explanation
                    FROM episodes_fts f
                    JOIN episodes e ON f.rowid = e.id
                    WHERE episodes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit))
                for row in cursor.fetchall():
                    results.append({
                        "repo_name": row[0],
                        "error_signature": row[1],
                        "resolution_patch": row[2],
                        "explanation": row[3],
                    })
        except Exception:
            pass
        return results
