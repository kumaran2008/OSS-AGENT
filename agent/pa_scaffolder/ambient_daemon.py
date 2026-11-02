from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from agent.pa_scaffolder.blackboard_kernel import blackboard
from agent.pa_scaffolder.kernel_governance import temporal_scheduler
from agent.pa_scaffolder.mode_kernel import AsyncKernelEventBus, event_bus as default_event_bus, mode_kernel
from agent.pa_scaffolder.unified_memory_hub import memory_hub
from agent.pa_scaffolder.universal_reader import universal_reader


class AmbientBackgroundDaemon:
    """Asynchronous Background Ambient Companion Daemon.
    Continuously monitors & reacts to:
      1. Due Temporal Reminders & Timers (`temporal_scheduler.check_due_reminders()`).
      2. Clipboard Traceback / Error Staging (automatically diagnoses copied stack traces into Blackboard).
      3. Cross-Platform OS Notifications with Household Emergency DND Triage.
    """

    ERROR_PATTERN = re.compile(
        r"(?:Traceback \(most recent call last\)|([A-Za-z0-9_]*(?:Error|Exception|Fault))\s*:\s*(.+))",
        flags=re.I,
    )

    def __init__(
        self,
        event_bus: Optional[AsyncKernelEventBus] = None,
        workspace_dir: str | Path = "workspace",
        poll_interval: float = 0.25,
        on_proactive_trigger: Optional[Callable[[Dict[str, Any]], Any]] = None,
        **kwargs: Any,
    ):
        self.event_bus = event_bus if event_bus is not None else default_event_bus
        self.workspace_dir = Path(workspace_dir)
        self.poll_interval = poll_interval
        self.on_proactive_trigger = on_proactive_trigger or kwargs.get("callback")
        self.extra_config = kwargs
        self._task: Optional[asyncio.Task[Any]] = None
        self._is_running = False
        self._last_slow_os_poll: float = 0.0
        self.event_bus.subscribe("CLIPBOARD_DIFF_DETECTED", self._on_clipboard_event)

    def _on_clipboard_event(self, event: Dict[str, Any]) -> None:
        snippet = event.get("payload", {}).get("clipboard_snippet", "")
        if snippet:
            self.stage_clipboard_diagnostic(snippet)

    def stage_clipboard_diagnostic(self, text: str) -> Optional[Dict[str, Any]]:
        """Inspects copied clipboard text for Python/shell errors and stages an instant fix in Blackboard."""
        if not self.ERROR_PATTERN.search(text):
            return None

        err_lines = [l.strip() for l in text.splitlines() if "error" in l.lower() or "exception" in l.lower()]
        err_sig = err_lines[-1] if err_lines else text.strip()[:120]

        past_fixes = memory_hub.episodic_exec.recall_similar_fix(err_sig, limit=1)
        if past_fixes:
            fix_hint = past_fixes[0].get("explanation") or past_fixes[0].get("fix_cmd", "")
        elif "keyerror" in err_sig.lower():
            fix_hint = "Use dict.get(key, default) to guard against missing dictionary keys."
        elif "syntaxerror" in err_sig.lower():
            fix_hint = "Check unescaped quotes, parentheses, or indentation on the reported line."
        elif "importerror" in err_sig.lower() or "modulenotfounderror" in err_sig.lower():
            fix_hint = "Verify virtual environment activation and module export name."
        else:
            fix_hint = "Wrap the failing call in a try/except block and inspect input types."

        diag_summary = f"Detected copied error ({err_sig[:80]}). Suggested remediation: {fix_hint}"
        blackboard.staged_diagnostic = diag_summary
        ev = self.event_bus.emit(
            "PROACTIVE_CLIPBOARD_DIAGNOSTIC",
            {"error_signature": err_sig, "suggested_fix": fix_hint, "diagnostic": diag_summary},
            source="ambient_daemon",
            priority=9,
        )
        temporal_scheduler.proactive_outbox.append({
            "type": "PROACTIVE_CLIPBOARD_DIAGNOSTIC",
            "spoken_alert": diag_summary,
            "timestamp": time.time(),
        })
        return ev

    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._poll_loop())
        except RuntimeError:
            pass

    def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def poll_once(self) -> None:
        """Executes a non-blocking scan of due SQLite reminders, in-memory notification queues,
        and throttled OS clipboard/notification bridges.
        """
        # 1. Fast sub-millisecond poll: Due Temporal Reminders in SQLite
        due_list = temporal_scheduler.check_due_reminders()
        for rem in due_list:
            ev = self.event_bus.emit(
                "TEMPORAL_REMINDER_DUE",
                {
                    "reminder_id": rem["reminder_id"],
                    "task_text": rem["task_text"],
                    "due_at": rem["due_at"],
                },
                source="temporal_scheduler",
                priority=9,
            )
            if self.on_proactive_trigger:
                try:
                    self.on_proactive_trigger(ev)
                except Exception:
                    pass

        # 2. Throttle slow external OS CLI subshells (e.g. termux-clipboard-get) to once every 5.0s
        now = time.time()
        if (now - getattr(self, "_last_slow_os_poll", 0.0)) >= 5.0:
            self._last_slow_os_poll = now
            loop = asyncio.get_running_loop()
            try:
                current_clip = await asyncio.wait_for(
                    loop.run_in_executor(None, universal_reader.read_clipboard),
                    timeout=0.4,
                )
                if current_clip and current_clip != blackboard.clipboard_text and "Clipboard is empty" not in current_clip:
                    blackboard.clipboard_text = current_clip
                    ev = self.event_bus.emit(
                        "CLIPBOARD_DIFF_DETECTED",
                        {"clipboard_snippet": current_clip[:160], "timestamp": now},
                        source="ambient_daemon",
                    )
                    self.stage_clipboard_diagnostic(current_clip)
            except Exception:
                pass

        # 3. Fast Poll: Proactive Notifications & Household DND Triage
        if universal_reader._live_notification_queue:
            triage = memory_hub.triage_proactive_notifications()
        else:
            triage = {"high_priority_count": 0}
        if triage.get("high_priority_count", 0) > 0:
            top_alert = triage["high_priority_alerts"][0]
            ev = self.event_bus.emit(
                "PROACTIVE_ALERT_EMERGENCY",
                {
                    "app": top_alert["app"],
                    "sender": top_alert["sender"],
                    "content": top_alert["content"],
                    "household_member": top_alert.get("household_member"),
                },
                source="ambient_daemon",
                priority=10,
            )
            if self.on_proactive_trigger:
                try:
                    self.on_proactive_trigger(ev)
                except Exception:
                    pass

    async def _poll_loop(self) -> None:
        while self._is_running:
            try:
                await self.poll_once()
                cadence = max(0.08, self.poll_interval)
                await asyncio.sleep(cadence)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.5)


AmbientObserverDaemon = AmbientBackgroundDaemon


def init_ambient_daemon(
    event_bus: Optional[AsyncKernelEventBus] = None,
    poll_interval: float = 0.15,
) -> AmbientBackgroundDaemon:
    return AmbientBackgroundDaemon(event_bus=event_bus, poll_interval=poll_interval)
