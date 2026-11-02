from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.memory_graph.memory_service import unified_memory_service
from agent.suites.builder_cursor_lovable.repository_intelligence import repo_intelligence
from agent.suites.news_intelligence.suite import news_intelligence_suite


class ProactiveDailyBriefingAssistant:
    """Section 10.3: Configurable Proactive Daily Briefing & Non-Intrusive Monitor.
    Compiles:
      1. Armed conditional task-linked reminders & scheduled alarms.
      2. Active project goals & coding architecture state from Unified Memory.
      3. Repository health & indexed AST symbol coverage.
      4. Verified AI/tech intelligence items in local timezone (IST).
      5. Non-intrusive delivery gate via TypeSafe `Jev` (`noul` focus check).
    """

    DB_PATH = Path("workspace/kernel_governance.db")
    IST_TZ = timezone(timedelta(hours=5, minutes=30))

    def get_armed_reminders_and_alarms(self) -> Dict[str, List[Dict[str, Any]]]:
        reminders: List[Dict[str, Any]] = []
        alarms: List[Dict[str, Any]] = []
        if not self.DB_PATH.exists():
            return {"conditional_reminders": reminders, "alarms": alarms}

        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            try:
                r_rows = conn.execute(
                    "SELECT reminder_id, trigger_condition, dependent_activity, reminder_text FROM conditional_task_reminders WHERE status = 'ARMED'"
                ).fetchall()
                reminders = [dict(r) for r in r_rows]
            except Exception:
                pass
            try:
                a_rows = conn.execute(
                    "SELECT alarm_id, label, trigger_spec, confidence FROM jev_alarms_and_timers WHERE status = 'ARMED' ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
                alarms = [dict(a) for a in a_rows]
            except Exception:
                pass
        return {"conditional_reminders": reminders, "alarms": alarms}

    def should_deliver_proactively_now(self, current_user_activity: str) -> Dict[str, Any]:
        """Uses TypeSafe `Jev` (`noul` primitive) so proactive briefings never interrupt
        competitive gaming, live streaming, or critical debugging unless urgent.
        """
        q_gate = {
            "user_is_in_do_not_disturb_activity": {
                "type": "noul",
                "affirmative_signals": ["competitive gaming", "ranked match", "live stream", "recording", "production outage"],
                "negative_signals": ["idle", "morning", "logged in", "normal mode", "finished task"],
            }
        }
        res = jev_ai_brain.evaluate_primitives(current_user_activity, q_gate)["user_is_in_do_not_disturb_activity"]
        deliver_now = not bool(res.value)
        return {
            "deliver_now": deliver_now,
            "delivery_mode": "IMMEDIATE_BRIEFING" if deliver_now else "QUEUED_SILENTLY_IN_HUD",
            "jev_confidence": res.confidence,
        }

    def generate_daily_briefing(self, current_user_activity: str = "morning workstation login") -> Dict[str, Any]:
        t0 = time.perf_counter()
        now_ist = datetime.now(self.IST_TZ)
        gate = self.should_deliver_proactively_now(current_user_activity)
        sched = self.get_armed_reminders_and_alarms()
        proj_mems = unified_memory_service.retrieve_scoped_memories(
            "active project architecture and primary database",
            allowed_namespaces=["coding_and_architecture", "ambitions_and_goals"],
            top_k=3,
        )
        repo_stats = repo_intelligence.index_repository(["agent/kernel", "agent/suites"])
        news_digest = news_intelligence_suite.compile_intelligence_briefing(
            topic="AI Systems & Developer Tools",
            time_range="LAST_7_DAYS",
            raw_feed_items=[
                {
                    "event_id": "jev_system1_update",
                    "title": "TypeSafe AI Jev 1.13.0 Calibrated System-1 Routing Benchmark",
                    "summary": "Demonstrates sub-10ms structured decision primitives (`noul`, `choice`, `score`).",
                    "event_date_iso": (now_ist - timedelta(days=1)).isoformat(),
                    "published_date_iso": (now_ist - timedelta(days=1)).isoformat(),
                    "is_official_source": True,
                    "source_url": "https://typesafe.ai/docs",
                }
            ],
            reference_now=now_ist,
        )
        return {
            "timestamp_ist": now_ist.isoformat(),
            "delivery_gate": gate,
            "armed_conditional_reminders": sched["conditional_reminders"],
            "armed_alarms": sched["alarms"],
            "active_project_memories": [m["content"] for m in proj_mems["results"]],
            "repository_health": {
                "files_indexed": repo_stats["files_indexed"],
                "total_symbols": repo_stats["total_symbols"],
            },
            "verified_news_count": news_digest["verified_items_count"],
            "generation_latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


proactive_assistant = ProactiveDailyBriefingAssistant()
