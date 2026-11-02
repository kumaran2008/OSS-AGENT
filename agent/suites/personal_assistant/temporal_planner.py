from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ConditionalTaskReminder:
    reminder_id: str
    trigger_condition: str         # e.g. "AFTER_TASK_COMPLETION:builder"
    dependent_activity: str
    reminder_text: str
    status: str                    # "ARMED" | "FIRED" | "CANCELLED"
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reminder_id": self.reminder_id,
            "trigger_condition": self.trigger_condition,
            "dependent_activity": self.dependent_activity,
            "reminder_text": self.reminder_text,
            "status": self.status,
            "created_at": self.created_at,
        }


class TemporalConditionalPlanner:
    """Section 10.1: Conditional Task-Linked Reminders.
    Understands current activity, future task, and the dependency between them
    without setting an arbitrary clock alarm when a task-state trigger is requested.
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conditional_task_reminders (
                    reminder_id TEXT PRIMARY KEY,
                    trigger_condition TEXT NOT NULL,
                    dependent_activity TEXT NOT NULL DEFAULT 'active_task',
                    reminder_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            existing_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(conditional_task_reminders)").fetchall()
            }
            if "dependent_activity" not in existing_cols:
                conn.execute(
                    "ALTER TABLE conditional_task_reminders ADD COLUMN dependent_activity TEXT NOT NULL DEFAULT 'active_task'"
                )
            conn.commit()

    @staticmethod
    def parse_activity_and_reminder(utterance: str) -> Optional[Dict[str, str]]:
        """Extracts arbitrary current activity and future reminder from natural speech."""
        low = utterance.lower()
        if "remind me" not in low or not any(k in low for k in ("after", "once", "when i finish", "when done")):
            return None

        # Extract current activity from "work on <X>", "working on <X>", "finish <X>"
        m_act = re.search(
            r"(?:work(?:ing)?\s+on\s+(?:the\s+)?|finish(?:ing)?\s+(?:the\s+)?)([a-zA-Z0-9_\-]+)",
            low,
        )
        activity = m_act.group(1).strip() if m_act else "active_task"
        if activity in ("i", "it", "this", "that", "today"):
            m_before = re.search(r"work(?:ing)?\s+on\s+(?:the\s+)?([a-zA-Z0-9_\-]+)", low)
            activity = m_before.group(1).strip() if m_before else "builder"

        m_rem = re.search(r"remind\s+me\s+(?:about\s+|to\s+)?(.+?)(?:\s+after\b|\s+once\b|\s+when\b|$)", utterance, flags=re.IGNORECASE)
        rem_text = m_rem.group(1).strip() if m_rem else utterance.strip()
        return {"activity": activity, "reminder_text": rem_text}

    def arm_conditional_reminder(self, task_dependency: str, reminder_text: str) -> ConditionalTaskReminder:
        rid = f"rem_{int(time.time() * 1000)}"
        clean_dep = task_dependency.lower().strip()
        cond = f"AFTER_TASK_COMPLETION:{clean_dep}"
        rem = ConditionalTaskReminder(
            reminder_id=rid,
            trigger_condition=cond,
            dependent_activity=clean_dep,
            reminder_text=reminder_text,
            status="ARMED",
            created_at=time.time(),
        )
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "DELETE FROM conditional_task_reminders WHERE trigger_condition = ? AND reminder_text = ? AND status = 'ARMED'",
                (cond, reminder_text),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO conditional_task_reminders (
                    reminder_id, trigger_condition, dependent_activity, reminder_text, status, created_at
                ) VALUES (?, ?, ?, ?, 'ARMED', ?)
                """,
                (rid, cond, clean_dep, reminder_text, rem.created_at),
            )
            conn.commit()
        return rem

    def check_and_fire_triggers(self, completed_task_tag: str) -> List[str]:
        target_cond = f"AFTER_TASK_COMPLETION:{completed_task_tag.lower().strip()}"
        fired_texts: List[str] = []
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT reminder_id, reminder_text FROM conditional_task_reminders WHERE trigger_condition = ? AND status = 'ARMED'",
                (target_cond,),
            ).fetchall()
            for r in rows:
                fired_texts.append(r["reminder_text"])
                conn.execute("UPDATE conditional_task_reminders SET status = 'FIRED' WHERE reminder_id = ?", (r["reminder_id"],))
            conn.commit()
        return fired_texts


temporal_planner = TemporalConditionalPlanner()
