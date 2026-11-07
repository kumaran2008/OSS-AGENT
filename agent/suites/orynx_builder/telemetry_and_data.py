from __future__ import annotations
import csv
import io
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SETTINGS_CATEGORIES: List[Dict[str, str]] = [
    {"id": "core", "label": "Core Settings", "description": "User profile and main settings"},
    {"id": "providers", "label": "Providers", "description": "API keys and provider configurations"},
    {"id": "features", "label": "Features", "description": "Feature flags and settings"},
    {"id": "ui", "label": "UI", "description": "UI configuration and preferences"},
    {"id": "connections", "label": "Connections", "description": "External service connections"},
    {"id": "debug", "label": "Debug", "description": "Debug settings and logs"},
    {"id": "updates", "label": "Updates", "description": "Update settings and notifications"},
]

API_KEY_TEMPLATE: Dict[str, str] = {
    "ANTHROPIC_API_KEY": "",
    "OPENAI_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "GOOGLE_GENERATIVE_AI_API_KEY": "",
    "OPEN_ROUTER_API_KEY": "",
    "GITHUB_API_KEY": "",
    "VITE_GITHUB_ACCESS_TOKEN": "",
    "VITE_GITLAB_ACCESS_TOKEN": "",
    "VITE_VERCEL_ACCESS_TOKEN": "",
    "VITE_NETLIFY_ACCESS_TOKEN": "",
    "VITE_SUPABASE_ACCESS_TOKEN": "",
}


class OrynxEventLogsAndDataStore:
    """
    Complete backend implementation of DataTab.tsx (`useDataOperations`, `useBoltHistoryDB`)
    and EventLogsTab.tsx (`logStore`, statistics, JSON/CSV/TXT/Report exports) in SQLite WAL.
    """

    def __init__(self, db_path: str = "workspace/kernel_governance.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_event_logs (
                    log_id TEXT PRIMARY KEY,
                    timestamp_iso TEXT,
                    level TEXT,
                    category TEXT,
                    message TEXT,
                    details_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_builder_chats (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    messages_json TEXT,
                    updated_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_settings_store (
                    category_id TEXT PRIMARY KEY,
                    settings_json TEXT,
                    updated_at REAL
                )
                """
            )
            for cat in SETTINGS_CATEGORIES:
                conn.execute(
                    "INSERT OR IGNORE INTO orynx_settings_store (category_id, settings_json, updated_at) VALUES (?, ?, ?)",
                    (cat["id"], json.dumps({"enabled": True, "label": cat["label"]}), time.time()),
                )

    # ---- EventLogsTab.tsx Operations ----
    def log_event(
        self,
        level: str,
        message: str,
        category: str = "system",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        log_id = f"log_{int(time.time() * 1000)}_{abs(hash((level, message, time.time()))) % 100000}"
        ts_iso = datetime.now(timezone.utc).isoformat()
        details_str = json.dumps(details or {})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO orynx_event_logs (log_id, timestamp_iso, level, category, message, details_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (log_id, ts_iso, level.lower(), category.lower(), message, details_str),
            )
        return {"id": log_id, "timestamp": ts_iso, "level": level.lower(), "category": category.lower(), "message": message}

    def log_performance_metric(self, component: str, metric_name: str, duration_ms: float) -> Dict[str, Any]:
        return self.log_event(
            level="debug",
            category="system",
            message=f"Performance metric {component}.{metric_name}: {round(duration_ms, 2)}ms",
            details={"component": component, "metric": metric_name, "duration_ms": round(duration_ms, 2)},
        )

    def query_logs(self, level_or_category: str = "all", search_query: str = "") -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT log_id, timestamp_iso, level, category, message, details_json FROM orynx_event_logs ORDER BY timestamp_iso DESC LIMIT 500"
            ).fetchall()
        results: List[Dict[str, Any]] = []
        q = search_query.lower().strip()
        for r in rows:
            lvl, cat, msg = r[2], r[3], r[4]
            if level_or_category != "all" and lvl != level_or_category and cat != level_or_category:
                continue
            if q and q not in msg.lower():
                continue
            results.append({
                "id": r[0],
                "timestamp": r[1],
                "level": lvl,
                "category": cat,
                "message": msg,
                "details": json.loads(r[5] or "{}"),
            })
        return results

    def compute_log_statistics(self, logs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
        items = logs if logs is not None else self.query_logs("all")
        return {
            "total": len(items),
            "error": sum(1 for x in items if x["level"] == "error"),
            "warning": sum(1 for x in items if x["level"] == "warning"),
            "info": sum(1 for x in items if x["level"] == "info"),
            "debug": sum(1 for x in items if x["level"] == "debug"),
            "provider": sum(1 for x in items if x["category"] == "provider"),
            "api": sum(1 for x in items if x["category"] == "api"),
        }

    def export_logs(self, fmt: str = "json", level_or_category: str = "all", search_query: str = "") -> str:
        filtered = self.query_logs(level_or_category, search_query)
        stats = self.compute_log_statistics(filtered)
        if fmt == "json":
            return json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "logs": filtered,
                "statistics": stats,
                "filters": {"level": level_or_category, "searchQuery": search_query},
            }, indent=2)
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
            writer.writerow(["Timestamp", "Level", "Category", "Message", "Details"])
            for log in filtered:
                writer.writerow([
                    log["timestamp"],
                    log["level"],
                    log["category"],
                    log["message"],
                    json.dumps(log["details"]),
                ])
            return buf.getvalue()
        lines: List[str] = [
            f"ORYNX BUILDER EVENT LOGS REPORT | Total={stats['total']} | Errors={stats['error']} | LLM={stats['provider']}",
            "=" * 80,
        ]
        for log in filtered:
            block = f"[{log['timestamp']}] {log['level'].upper()}: {log['message']}\nCategory: {log['category']}\n"
            if log["details"]:
                block += f"Details:\n{json.dumps(log['details'], indent=2)}\n"
            block += ("-" * 80)
            lines.append(block)
        return "\n".join(lines)

    # ---- DataTab.tsx (`useDataOperations`) Operations ----
    def save_chat(self, chat_id: str, title: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orynx_builder_chats (chat_id, title, description, messages_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, title, f"{len(messages)} messages", json.dumps(messages), now),
            )
        return {"id": chat_id, "label": title, "messages_count": len(messages), "updatedAt": now}

    def export_selected_chats(self, selected_ids: Optional[List[str]] = None) -> str:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT chat_id, title, description, messages_json, updated_at FROM orynx_builder_chats").fetchall()
        chats = [
            {"id": r[0], "title": r[1], "description": r[2], "messages": json.loads(r[3] or "[]"), "updatedAt": r[4]}
            for r in rows
            if selected_ids is None or r[0] in selected_ids
        ]
        return json.dumps({"exportedAt": datetime.now(timezone.utc).isoformat(), "chats": chats}, indent=2)

    def export_selected_settings(self, selected_category_ids: Optional[List[str]] = None) -> str:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT category_id, settings_json, updated_at FROM orynx_settings_store").fetchall()
        out = {
            r[0]: {"settings": json.loads(r[1] or "{}"), "updatedAt": r[2]}
            for r in rows
            if selected_category_ids is None or r[0] in selected_category_ids
        }
        return json.dumps({"exportedAt": datetime.now(timezone.utc).isoformat(), "settings": out}, indent=2)

    def download_api_key_template(self) -> str:
        return json.dumps(API_KEY_TEMPLATE, indent=2)
