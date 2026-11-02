from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.pa_scaffolder.kernel_governance import enforce_owner_only_permissions, secret_scrubber


@dataclass
class UndoRecord:
    action_id: str
    action_type: str
    description: str
    rollback_fn: Optional[Callable[[], str]]
    reversibility: str = "REVERSIBLE"  # "REVERSIBLE" | "COMPENSATABLE" | "IRREVERSIBLE"
    status: str = "SUCCEEDED"
    pre_state_hash: str = ""
    post_state_hash: str = ""
    timestamp: float = field(default_factory=time.time)


class ReversibleUndoLedger:
    """Persistent Action Journal & Recovery System ('Friday, undo that').
    - Persists every action audit record to SQLite (`action_journal`).
    - Distinguishes REVERSIBLE (local DB/file edits) from IRREVERSIBLE (outbound messages/emails).
    - Supports cryptographic SHA-256 file-diff backups and verified disk restoration.
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self, max_depth: int = 50):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._stack: List[List[UndoRecord]] = []
        self._current_turn_records: List[UndoRecord] = []
        self.max_depth = max_depth
        self._init_db()
        enforce_owner_only_permissions(self.DB_PATH)

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_journal (
                    action_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reversibility TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pre_state_hash TEXT,
                    post_state_hash TEXT,
                    backup_payload_json TEXT,
                    timestamp REAL
                )
                """
            )
            conn.commit()

    def _persist_journal_entry(
        self,
        rec: UndoRecord,
        backup_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO action_journal (
                    action_id, action_type, description, reversibility,
                    status, pre_state_hash, post_state_hash, backup_payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.action_id,
                    rec.action_type,
                    rec.description,
                    rec.reversibility,
                    rec.status,
                    rec.pre_state_hash,
                    rec.post_state_hash,
                    json.dumps(backup_payload or {}),
                    rec.timestamp,
                ),
            )
            conn.commit()

    def begin_turn(self) -> None:
        self._current_turn_records = []

    def commit_turn(self) -> None:
        has_mutation = any(r.action_type != "EPISODIC_TURN" for r in self._current_turn_records)
        if has_mutation:
            self._stack.append(list(self._current_turn_records))
            if len(self._stack) > self.max_depth:
                self._stack.pop(0)
        self._current_turn_records = []

    def register_undo(
        self,
        action_type: str,
        description: str,
        rollback_fn: Optional[Callable[[], str]] = None,
        reversibility: str = "REVERSIBLE",
        pre_state_hash: str = "",
        post_state_hash: str = "",
        backup_payload: Optional[Dict[str, Any]] = None,
    ) -> UndoRecord:
        rec = UndoRecord(
            action_id=f"act_{int(time.time() * 1000)}_{len(self._current_turn_records)}",
            action_type=action_type,
            description=description,
            rollback_fn=rollback_fn,
            reversibility=reversibility,
            status="SUCCEEDED",
            pre_state_hash=pre_state_hash,
            post_state_hash=post_state_hash,
        )
        self._current_turn_records.append(rec)
        if action_type != "EPISODIC_TURN":
            self._persist_journal_entry(rec, backup_payload=backup_payload)
        return rec

    def execute_reversible_file_edit(
        self,
        file_path: str | Path,
        new_content: str,
        description: str = "Modified workspace file",
    ) -> Dict[str, Any]:
        p = Path(file_path)
        existed_before = p.exists()
        old_bytes = p.read_bytes() if existed_before else b""
        pre_hash = hashlib.sha256(old_bytes).hexdigest()[:16] if existed_before else "NEW_FILE"

        p.parent.mkdir(parents=True, exist_ok=True)
        new_bytes = new_content.encode("utf-8")
        p.write_bytes(new_bytes)
        post_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:16]

        def _rollback_file() -> str:
            if not existed_before:
                if p.exists():
                    p.unlink()
                return f"Removed newly created file {p.name}."
            p.write_bytes(old_bytes)
            restored_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            verified = "verified SHA-256 match" if restored_hash == pre_hash else "hash mismatch"
            return f"Restored {p.name} to pre-edit state ({verified}: {restored_hash})."

        rec = self.register_undo(
            action_type="FILE_EDIT",
            description=f"{description} ({p.name})",
            rollback_fn=_rollback_file,
            reversibility="REVERSIBLE",
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
            backup_payload={
                "file_path": str(p),
                "existed_before": existed_before,
                "old_content": old_bytes.decode("utf-8", errors="ignore"),
            },
        )
        return {
            "action_id": rec.action_id,
            "file_path": str(p),
            "pre_state_hash": pre_hash,
            "post_state_hash": post_hash,
        }

    def undo_last(self) -> Dict[str, Any]:
        if not self._stack and not self._current_turn_records:
            return {
                "intent": "UNDO_ACTION",
                "status": "empty",
                "spoken_response": "Nothing to undo in the action journal, sir.",
            }

        records = self._stack.pop() if self._stack else list(self._current_turn_records)
        self._current_turn_records = []

        reverted_summaries: List[str] = []
        irreversible_notices: List[str] = []

        for rec in reversed(records):
            if rec.reversibility == "IRREVERSIBLE":
                if rec.action_type != "EPISODIC_TURN":
                    irreversible_notices.append(f"'{rec.description}' is an external IRREVERSIBLE action and cannot be recalled once dispatched")
                    with sqlite3.connect(self.DB_PATH) as conn:
                        conn.execute("UPDATE action_journal SET status = 'IRREVERSIBLE_REFUSED' WHERE action_id = ?", (rec.action_id,))
                        conn.commit()
                continue
            if rec.rollback_fn is None:
                continue
            try:
                msg = rec.rollback_fn()
                if msg:
                    reverted_summaries.append(msg)
                with sqlite3.connect(self.DB_PATH) as conn:
                    conn.execute("UPDATE action_journal SET status = 'REVERTED' WHERE action_id = ?", (rec.action_id,))
                    conn.commit()
            except Exception as e:
                reverted_summaries.append(f"Failed to revert {rec.description}: {e}")

        if irreversible_notices and not reverted_summaries:
            combined = " | ".join(irreversible_notices)
            return {
                "intent": "UNDO_ACTION",
                "status": "irreversible",
                "reverted_count": 0,
                "spoken_response": f"Action Journal Notice: {combined}.",
            }

        all_msgs = reverted_summaries + irreversible_notices
        combined = " | ".join(all_msgs)
        return {
            "intent": "UNDO_ACTION",
            "status": "reverted",
            "reverted_count": len(reverted_summaries),
            "spoken_response": f"Undid last action: {combined}",
        }


@dataclass
class ExecutionPipeContext:
    """Carries output artifacts and taint provenance from Sub-Task N to Sub-Task N+1."""

    last_output: str = ""
    last_file_path: str = ""
    last_image_path: str = ""
    last_person: str = ""
    last_ui_label: str = ""
    taint_level: str = "TRUSTED"  # "TRUSTED" | "UNTRUSTED_EXTERNAL"
    taint_source: str = ""
    step_outputs: List[Dict[str, Any]] = field(default_factory=list)

    UNTRUSTED_INTENTS = {
        "PROACTIVE_NOTIFICATION_TRIAGE",
        "READ_NOTIFICATIONS",
        "READ_WHATSAPP",
        "YOUTUBE_TRANSCRIPT_INGESTED",
        "READ_YOUTUBE",
    }

    def absorb(self, result: Dict[str, Any]) -> None:
        self.step_outputs.append(result)
        intent = result.get("intent", "")
        if intent in self.UNTRUSTED_INTENTS or result.get("taint_level") == "UNTRUSTED_EXTERNAL":
            self.taint_level = "UNTRUSTED_EXTERNAL"
            self.taint_source = intent

        spoken = result.get("spoken_response", "")
        raw_out = result.get("output") or spoken
        if raw_out:
            scrubbed, _ = secret_scrubber.scrub(str(raw_out).strip())
            self.last_output = scrubbed

        if result.get("file"):
            self.last_file_path = str(result["file"])
        if result.get("file_path"):
            self.last_image_path = str(result["file_path"])

        if result.get("name"):
            self.last_person = str(result["name"])
        elif result.get("recipient"):
            self.last_person = str(result["recipient"])
        elif result.get("analysis", {}).get("person_info", {}).get("name"):
            self.last_person = str(result["analysis"]["person_info"]["name"])
        elif result.get("high_priority_alerts"):
            top_alert = result["high_priority_alerts"][0]
            if top_alert.get("household_member"):
                self.last_person = str(top_alert["household_member"])

        ui_elems = result.get("analysis", {}).get("ui_elements", [])
        if ui_elems and isinstance(ui_elems, list):
            self.last_ui_label = str(ui_elems[0].get("label", ""))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_output": self.last_output,
            "last_file_path": self.last_file_path,
            "last_image_path": self.last_image_path,
            "last_person": self.last_person,
            "last_ui_label": self.last_ui_label,
            "taint_level": self.taint_level,
            "taint_source": self.taint_source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPipeContext":
        return cls(
            last_output=data.get("last_output", ""),
            last_file_path=data.get("last_file_path", ""),
            last_image_path=data.get("last_image_path", ""),
            last_person=data.get("last_person", ""),
            last_ui_label=data.get("last_ui_label", ""),
            taint_level=data.get("taint_level", "TRUSTED"),
            taint_source=data.get("taint_source", ""),
        )


@dataclass
class ContextSlot:
    value: str = ""
    timestamp: float = 0.0
    ttl_seconds: float = 300.0
    provenance: str = "SYSTEM_DEFAULT"
    scope: str = "normal"
    taint_level: str = "TRUSTED"
    allow_remote_processing: bool = True

    def is_fresh(self, now: Optional[float] = None) -> bool:
        if not self.value:
            return False
        curr = now if now is not None else time.time()
        return (curr - self.timestamp) <= self.ttl_seconds


class ActiveContextBlackboard:
    """SQLite-Persisted, Permission-Aware, TTL-Scoped Working Memory Blackboard.
    Survives terminal and process restarts via `kernel_state_kv` in `workspace/kernel_governance.db`.
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self, default_ttl: float = 300.0):
        self.default_ttl = default_ttl
        self.privacy_paused: bool = False
        self.current_scope: str = "normal"
        self.focused_window: str = "Workstation_Terminal"
        self._slots: Dict[str, ContextSlot] = {
            "clipboard_text": ContextSlot(ttl_seconds=default_ttl),
            "active_file": ContextSlot(ttl_seconds=default_ttl),
            "last_image_path": ContextSlot(ttl_seconds=default_ttl),
            "last_person": ContextSlot(ttl_seconds=default_ttl),
            "last_ui_label": ContextSlot(ttl_seconds=default_ttl),
            "last_output": ContextSlot(ttl_seconds=default_ttl),
            "staged_diagnostic": ContextSlot(ttl_seconds=default_ttl),
        }
        self.last_intent: str = ""
        self.updated_at: float = time.time()
        self._init_kv_db()
        self.load_from_disk()

    def _init_kv_db(self) -> None:
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kernel_state_kv (
                    slot_key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    ttl_seconds REAL NOT NULL,
                    provenance TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    taint_level TEXT NOT NULL,
                    allow_remote INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def _persist_slot_to_disk(self, key: str, slot: ContextSlot) -> None:
        try:
            with sqlite3.connect(self.DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO kernel_state_kv (
                        slot_key, value, timestamp, ttl_seconds, provenance, scope, taint_level, allow_remote
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        slot.value,
                        slot.timestamp,
                        slot.ttl_seconds,
                        slot.provenance,
                        slot.scope,
                        slot.taint_level,
                        1 if slot.allow_remote_processing else 0,
                    ),
                )
                conn.commit()
        except Exception:
            pass

    def load_from_disk(self) -> None:
        """Hydrates Blackboard working memory slots from SQLite across process restarts."""
        try:
            with sqlite3.connect(self.DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute("SELECT * FROM kernel_state_kv").fetchall():
                    slot = ContextSlot(
                        value=row["value"],
                        timestamp=float(row["timestamp"]),
                        ttl_seconds=float(row["ttl_seconds"]),
                        provenance=row["provenance"],
                        scope=row["scope"],
                        taint_level=row["taint_level"],
                        allow_remote_processing=bool(row["allow_remote"]),
                    )
                    if slot.is_fresh():
                        self._slots[row["slot_key"]] = slot
        except Exception:
            pass

    def set_slot(
        self,
        key: str,
        value: str,
        provenance: str = "TOOL_OUTPUT",
        ttl_seconds: Optional[float] = None,
        taint_level: str = "TRUSTED",
    ) -> ContextSlot:
        if self.privacy_paused and provenance in ("SCREEN_OBSERVED", "CLIPBOARD_SENSED"):
            return self._slots.get(key, ContextSlot())

        scrubbed_val, had_secret = secret_scrubber.scrub(str(value))
        slot = ContextSlot(
            value=scrubbed_val,
            timestamp=time.time(),
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl,
            provenance=provenance,
            scope=self.current_scope,
            taint_level=taint_level,
            allow_remote_processing=not had_secret,
        )
        self._slots[key] = slot
        self.updated_at = slot.timestamp
        self._persist_slot_to_disk(key, slot)
        return slot

    def get_slot_meta(self, key: str) -> ContextSlot:
        return self._slots.get(key, ContextSlot())

    def get_fresh_value(self, key: str) -> str:
        slot = self._slots.get(key)
        if slot and slot.is_fresh():
            return slot.value
        return ""

    def expire_slot(self, key: str) -> None:
        if key in self._slots:
            self._slots[key].timestamp = 0.0
            self._persist_slot_to_disk(key, self._slots[key])

    @property
    def clipboard_text(self) -> str:
        return self.get_fresh_value("clipboard_text")

    @clipboard_text.setter
    def clipboard_text(self, val: str) -> None:
        self.set_slot("clipboard_text", val, provenance="CLIPBOARD_SENSED")

    @property
    def active_file(self) -> str:
        return self.get_fresh_value("active_file")

    @active_file.setter
    def active_file(self, val: str) -> None:
        self.set_slot("active_file", val, provenance="USER_EXPLICIT")

    @property
    def last_image_path(self) -> str:
        return self.get_fresh_value("last_image_path")

    @last_image_path.setter
    def last_image_path(self, val: str) -> None:
        self.set_slot("last_image_path", val, provenance="SCREEN_OBSERVED")

    @property
    def last_person(self) -> str:
        return self.get_fresh_value("last_person")

    @last_person.setter
    def last_person(self, val: str) -> None:
        self.set_slot("last_person", val, provenance="USER_EXPLICIT")

    @property
    def last_ui_label(self) -> str:
        return self.get_fresh_value("last_ui_label")

    @last_ui_label.setter
    def last_ui_label(self, val: str) -> None:
        self.set_slot("last_ui_label", val, provenance="SCREEN_OBSERVED")

    @property
    def last_output(self) -> str:
        return self.get_fresh_value("last_output")

    @last_output.setter
    def last_output(self, val: str) -> None:
        self.set_slot("last_output", val, provenance="TOOL_OUTPUT")


    @property
    def staged_diagnostic(self) -> str:
        return self.get_fresh_value("staged_diagnostic")

    @staged_diagnostic.setter
    def staged_diagnostic(self, val: str) -> None:
        self.set_slot("staged_diagnostic", val, provenance="CLIPBOARD_SENSED")

    def snapshot_state(self) -> Dict[str, Any]:
        return {
            "active_file": self.active_file,
            "last_image_path": self.last_image_path,
            "last_person": self.last_person,
            "last_ui_label": self.last_ui_label,
            "last_output": self.last_output,
        }

    def restore_state(self, snapshot: Dict[str, Any]) -> None:
        for k, v in snapshot.items():
            if v:
                self.set_slot(k, str(v), provenance="MODE_RESTORED")

    def update_from_result(self, user_prompt: str, result: Dict[str, Any]) -> None:
        intent = result.get("intent", "")
        if intent == "UNDO_ACTION":
            return

        self.last_intent = intent
        taint = "UNTRUSTED_EXTERNAL" if intent in ExecutionPipeContext.UNTRUSTED_INTENTS else "TRUSTED"
        spoken = result.get("spoken_response", "")
        raw_out = result.get("output") or spoken
        if raw_out:
            self.set_slot("last_output", str(raw_out).strip(), provenance="TOOL_OUTPUT", taint_level=taint)

        if result.get("file"):
            self.set_slot("active_file", str(result["file"]), provenance="TOOL_OUTPUT")
        else:
            fm = re.search(r"([a-zA-Z0-9_\-\./]+\.(?:py|md|txt|json|pdf|docx|sh|yaml|yml))\b", user_prompt)
            if fm:
                self.set_slot("active_file", fm.group(1), provenance="USER_EXPLICIT")

        if result.get("file_path"):
            self.set_slot("last_image_path", str(result["file_path"]), provenance="SCREEN_OBSERVED")

        if result.get("name"):
            self.set_slot("last_person", str(result["name"]), provenance="USER_EXPLICIT")
        elif result.get("recipient"):
            self.set_slot("last_person", str(result["recipient"]), provenance="USER_EXPLICIT")
        elif result.get("analysis", {}).get("person_info", {}).get("name"):
            self.set_slot("last_person", str(result["analysis"]["person_info"]["name"]), provenance="SCREEN_OBSERVED")
        elif result.get("high_priority_alerts"):
            top_alert = result["high_priority_alerts"][0]
            if top_alert.get("household_member"):
                self.set_slot("last_person", str(top_alert["household_member"]), provenance="TOOL_OUTPUT")

        ui_elems = result.get("analysis", {}).get("ui_elements", [])
        if ui_elems and isinstance(ui_elems, list):
            self.set_slot("last_ui_label", str(ui_elems[0].get("label", "")), provenance="SCREEN_OBSERVED")

    def resolve_deictics(self, task_prompt: str, pipe_ctx: Optional[ExecutionPipeContext] = None) -> str:
        resolved = task_prompt.strip()
        lower = resolved.lower()

        piped_out = (pipe_ctx.last_output if pipe_ctx and pipe_ctx.last_output else self.last_output).strip()
        active_file = (pipe_ctx.last_file_path if pipe_ctx and pipe_ctx.last_file_path else self.active_file).strip()
        active_img = (pipe_ctx.last_image_path if pipe_ctx and pipe_ctx.last_image_path else self.last_image_path).strip()
        active_person = (pipe_ctx.last_person if pipe_ctx and pipe_ctx.last_person else self.last_person).strip()
        active_ui = (pipe_ctx.last_ui_label if pipe_ctx and pipe_ctx.last_ui_label else self.last_ui_label).strip()

        # 1. Piped Memory Storage
        if re.match(
            r"^(?:please\s+)?(?:remember|note|save)\s+(?:that|this|it|the\s+output|the\s+result|the\s+summary)(?:\s+to\s+memory|\s+in\s+memory)?\s*$",
            lower,
        ):
            if piped_out:
                clean_fact = re.sub(r"\s+", " ", piped_out)[:220]
                return f"Remember that {clean_fact}"

        # 2. Pronoun File Slicing or Continuing Reading ("continue reading it", "read lines 5 to 8 from it")
        if active_file and re.search(r"\b(?:find\s+the\s+(?:section|chapter|part)|jump\s+to).*?\b(?:in|inside|from)\s+(?:it|that|this|my\s+book|the\s+book)\b", lower):
            resolved = re.sub(r"\b(?:in|inside|from)\s+(?:it|that|this|my\s+book|the\s+book)\b", f"in {active_file}", resolved, flags=re.I)
        elif active_file and re.search(r"\b(?:continue\s+reading|resume\s+reading|keep\s+reading)\s+(?:it|that|this|my\s+book|the\s+book|the\s+file)\b", lower):
            resolved = f"Continue reading {active_file}"
        elif ("line" in lower and "read" in lower) and active_file:
            if re.search(r"\b(?:from|in|of)\s+(?:it|that|this|that\s+file|this\s+file|the\s+same\s+file)\b", lower):
                resolved = re.sub(
                    r"\b(?:from|in|of)\s+(?:it|that|this|that\s+file|this\s+file|the\s+same\s+file)\b",
                    f"from {active_file}",
                    resolved,
                    flags=re.I,
                )
            elif not re.search(r"\b[a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]+\b", resolved):
                resolved = f"{resolved} from {active_file}"

        # 3. Person Pronoun Resolution ("reply to him that...", "check notifications from him")
        if active_person and re.search(r"\b(?:him|her|that\s+person)\b", lower):
            resolved = re.sub(r"\b(?:him|her|that\s+person)\b", active_person, resolved, flags=re.I)

        # 4. Image / Photo Pronoun Resolution
        if active_img and re.search(r"\b(?:analyze|ingest|scan|inspect)\s+(?:it|that|this|that\s+photo|this\s+photo|that\s+image)\b", lower):
            resolved = re.sub(
                r"\b(?:it|that|this|that\s+photo|this\s+photo|that\s+image)\b",
                active_img,
                resolved,
                flags=re.I,
            )

        # 5. UI Element Pronoun Resolution
        if active_ui and re.match(r"^(?:please\s+)?(?:click|tap|press)\s+(?:on\s+)?(?:it|that|this|that\s+button|the\s+first\s+element)\b", lower):
            resolved = f"Click {active_ui}"

        return resolved


blackboard = ActiveContextBlackboard()
undo_ledger = ReversibleUndoLedger()
