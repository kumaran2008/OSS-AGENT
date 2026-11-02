from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class KernelStateStore:
    """5-Tier Trustworthy Personal Memory System (Reviewer Improvement 2).
    Memory Tiers:
      1. PREFERENCE          : How the user likes to work, communicate, study, and organize their day.
      2. LONG_TERM_KNOWLEDGE : Facts the user explicitly wants remembered.
      3. PROJECT_CONTEXT     : Current codebases, documents, unfinished work, and ongoing goals.
      4. TEMPORARY_CONTEXT   : Active screen, conversation, or ephemeral session state.
      5. EXPERIENCE_RECORD   : Which workflows succeeded, failed, and what evidence was obtained.
    Includes provenance, freshness TTL, confidence (0.0-1.0), origin_type (INFERRED_BY_AGENT vs USER_CONFIRMED),
    and full user CRUD controls (inspect, correct, export, delete).
    """

    DB_PATH = Path("workspace/kernel_governance.db")
    VALID_TIERS = {
        "PREFERENCE",
        "LONG_TERM_KNOWLEDGE",
        "PROJECT_CONTEXT",
        "TEMPORARY_CONTEXT",
        "EXPERIENCE_RECORD",
    }

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def blackboard(self):
        from agent.pa_scaffolder.blackboard_kernel import blackboard
        return blackboard

    @property
    def undo_ledger(self):
        from agent.pa_scaffolder.blackboard_kernel import undo_ledger
        return undo_ledger

    @property
    def memory_hub(self):
        from agent.pa_scaffolder.unified_memory_hub import memory_hub
        return memory_hub

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trust_carrying_memories (
                    memory_id TEXT PRIMARY KEY,
                    memory_tier TEXT DEFAULT 'LONG_TERM_KNOWLEDGE',
                    content TEXT NOT NULL,
                    source_provenance TEXT NOT NULL,
                    origin_type TEXT DEFAULT 'USER_CONFIRMED',
                    confidence REAL DEFAULT 1.0,
                    trust_level TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    allow_permanent_index INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            # Ensure new columns exist if table was created in an earlier stage
            existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(trust_carrying_memories)").fetchall()}
            if "memory_tier" not in existing_cols:
                conn.execute("ALTER TABLE trust_carrying_memories ADD COLUMN memory_tier TEXT DEFAULT 'LONG_TERM_KNOWLEDGE'")
            if "origin_type" not in existing_cols:
                conn.execute("ALTER TABLE trust_carrying_memories ADD COLUMN origin_type TEXT DEFAULT 'USER_CONFIRMED'")
            if "confidence" not in existing_cols:
                conn.execute("ALTER TABLE trust_carrying_memories ADD COLUMN confidence REAL DEFAULT 1.0")
            conn.commit()

    def record_trust_tagged_memory(
        self,
        content: str,
        source_provenance: str = "USER_EXPLICIT",
        trust_level: str = "TRUSTED_USER",
        sensitivity: str = "PUBLIC",
        scope: str = "global",
        ttl_seconds: float = 86400.0 * 30,
        memory_tier: str = "LONG_TERM_KNOWLEDGE",
        origin_type: str = "USER_CONFIRMED",
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        now = time.time()
        tier = memory_tier if memory_tier in self.VALID_TIERS else "LONG_TERM_KNOWLEDGE"
        # Inferred preferences or private communications are blocked from permanent global indexing by default
        if origin_type == "INFERRED_BY_AGENT":
            confidence = min(float(confidence), 0.65)
        allow_perm = 1 if (
            trust_level == "TRUSTED_USER"
            and sensitivity != "PRIVATE_COMM"
            and origin_type == "USER_CONFIRMED"
            and confidence >= 0.80
        ) else 0

        if sensitivity == "PRIVATE_COMM" or tier == "TEMPORARY_CONTEXT":
            ttl_seconds = min(ttl_seconds, 1800.0)

        mem_id = f"tcm_{hashlib.md5(f'{tier}:{content}'.encode()).hexdigest()[:10]}"
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_carrying_memories (
                    memory_id, memory_tier, content, source_provenance, origin_type,
                    confidence, trust_level, sensitivity, scope, allow_permanent_index,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mem_id,
                    tier,
                    content[:500],
                    source_provenance,
                    origin_type,
                    round(float(confidence), 3),
                    trust_level,
                    sensitivity,
                    scope,
                    allow_perm,
                    now,
                    now + ttl_seconds,
                ),
            )
            conn.commit()
        return {
            "memory_id": mem_id,
            "memory_tier": tier,
            "origin_type": origin_type,
            "confidence": round(float(confidence), 3),
            "trust_level": trust_level,
            "sensitivity": sensitivity,
            "allow_permanent_index": bool(allow_perm),
        }

    # ---- User Control CRUD: Inspect, Correct, Export, Delete ----
    def inspect_memories(self, memory_tier: Optional[str] = None, include_expired: bool = False) -> List[Dict[str, Any]]:
        now = time.time()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            q = "SELECT * FROM trust_carrying_memories WHERE 1=1"
            params: List[Any] = []
            if not include_expired:
                q += " AND expires_at > ?"
                params.append(now)
            if memory_tier:
                q += " AND memory_tier = ?"
                params.append(memory_tier)
            q += " ORDER BY created_at DESC"
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    def correct_memory(self, memory_id: str, new_content: str, confirm_by_user: bool = True) -> Dict[str, Any]:
        origin = "USER_CONFIRMED" if confirm_by_user else "INFERRED_BY_AGENT"
        conf = 1.0 if confirm_by_user else 0.65
        with sqlite3.connect(self.DB_PATH) as conn:
            cur = conn.execute(
                """
                UPDATE trust_carrying_memories
                SET content = ?, origin_type = ?, confidence = ?, allow_permanent_index = ?
                WHERE memory_id = ?
                """,
                (new_content[:500], origin, conf, 1 if confirm_by_user else 0, memory_id),
            )
            conn.commit()
            updated = cur.rowcount > 0
        return {"memory_id": memory_id, "updated": updated, "new_content": new_content, "origin_type": origin, "confidence": conf}

    def delete_memory(self, memory_id: str) -> Dict[str, Any]:
        content_snip = ""
        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute("SELECT content FROM trust_carrying_memories WHERE memory_id = ?", (memory_id,)).fetchone()
            if row:
                content_snip = row[0]
            cur = conn.execute("DELETE FROM trust_carrying_memories WHERE memory_id = ?", (memory_id,))
            conn.commit()
            deleted = cur.rowcount > 0
        graph_purged = 0
        try:
            if content_snip and hasattr(self.memory_hub.graph_brain, "purge_memory_nodes_matching"):
                graph_purged = self.memory_hub.graph_brain.purge_memory_nodes_matching(content_snip)
            self.memory_hub.graph_brain._cache_dirty = True
        except Exception:
            pass
        return {"memory_id": memory_id, "deleted": deleted, "graph_nodes_purged": graph_purged}

    def export_memories(self, export_path: str | Path = "workspace/exported_personal_memories.json") -> Dict[str, Any]:
        records = self.inspect_memories(include_expired=False)
        p = Path(export_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"exported_at": time.time(), "count": len(records), "memories": records}, indent=2), encoding="utf-8")
        return {"export_path": str(p), "exported_count": len(records)}


state_store = KernelStateStore()
