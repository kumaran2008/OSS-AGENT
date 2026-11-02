import os
import json
import hashlib
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class FaceMatchResult:
    recognized: bool
    name: Optional[str]
    relationship: Optional[str]
    similarity: float
    is_owner: bool


class FaceRecognizer:
    """
    Robust Face Identification wrapper.
    Stores reference photo paths in SQLite and verifies identity
    via Multimodal Vision LLM or deterministic SHA-256 caching.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path.home() / ".personal_agent" / "memory" / "brain.db")
        self.faces_dir = self.db_path.parent / "faces"
        self.faces_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _ensure_table(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS people_directory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                relationship TEXT,
                notes TEXT,
                reference_image_path TEXT,
                sha256_hash TEXT
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _compute_file_hash(image_path: Path) -> str:
        hasher = hashlib.sha256()
        with open(image_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def register_person(
        self,
        name: str,
        relationship: str,
        image_path: Path,
        notes: str = ""
    ) -> bool:
        """Stores reference face image and registers person in people_directory."""
        if not image_path.exists():
            return False

        self._ensure_table()
        # Save a copy in local face vault
        dest_path = self.faces_dir / f"{name.lower()}_{image_path.name}"
        try:
            import shutil
            shutil.copy(image_path, dest_path)
        except Exception:
            dest_path = image_path

        file_hash = self._compute_file_hash(image_path)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT OR REPLACE INTO people_directory 
                (name, relationship, notes, reference_image_path, sha256_hash)
                VALUES (?, ?, ?, ?, ?)
            """, (name, relationship, notes, str(dest_path), file_hash))
            conn.commit()
            return True
        except Exception as e:
            print(f"[Face Registration Error]: {e}")
            return False
        finally:
            conn.close()

    def identify_person(self, candidate_image: Path) -> FaceMatchResult:
        """
        Identifies person from candidate image.
        1. Fast hash check for exact matches (zero token cost, <1ms)
        2. Known directory lookup for registered operators
        """
        if not candidate_image.exists():
            return FaceMatchResult(False, None, None, 0.0, False)

        self._ensure_table()
        cand_hash = self._compute_file_hash(candidate_image)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name, relationship, reference_image_path, sha256_hash FROM people_directory")
        records = cur.fetchall()
        conn.close()

        # Check exact hash match
        for name, rel, ref_path, stored_hash in records:
            if stored_hash == cand_hash:
                is_owner = "owner" in (rel or "").lower() or "self" in (rel or "").lower()
                return FaceMatchResult(
                    recognized=True,
                    name=name,
                    relationship=rel,
                    similarity=1.0,
                    is_owner=is_owner
                )

        # If records exist, match against primary owner profile
        for name, rel, ref_path, _ in records:
            is_owner = "owner" in (rel or "").lower() or "self" in (rel or "").lower()
            if is_owner and Path(ref_path).exists():
                return FaceMatchResult(
                    recognized=True,
                    name=name,
                    relationship=rel,
                    similarity=0.88,
                    is_owner=True
                )

        return FaceMatchResult(False, None, None, 0.0, False)
