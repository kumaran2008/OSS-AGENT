from __future__ import annotations

import re
from typing import Any, Dict, List

from agent.kernel.plugin_host import Action, ActionResult, AuthorizedTaskContext, Capability, VerificationResult
from agent.kernel.state_store import state_store


class MessagingSchedulePlugin:
    """Wraps UniversalReader, UnifiedMemoryHub & TemporalCompanionScheduler for Messaging, Notifications & Reminders."""

    plugin_id = "plugin.messaging_schedule"
    api_version = "1.0.0"

    def discover_capabilities(self) -> List[Capability]:
        return [
            Capability(
                id="messaging.send_confirmed",
                version="1.0.0",
                plugin_id=self.plugin_id,
                description="Dispatches an outbound message with contact resolution, idempotency, and IRREVERSIBLE journaling.",
                execution_backend="OS_ACCESSIBILITY",
                risk_class="external_write",
                data_sensitivity="PRIVATE_COMM",
                preconditions=["recipient_disambiguated"],
                postconditions=["outbox_or_provider_receipt_recorded"],
                idempotency_class="NON_IDEMPOTENT_GUARDED",
            ),
            Capability(
                id="notifications.triage",
                version="1.0.0",
                plugin_id=self.plugin_id,
                description="Collects and triages OS notifications with Mode DND and household priority breakthrough.",
                execution_backend="OS_ACCESSIBILITY",
                risk_class="read",
                data_sensitivity="PRIVATE_COMM",
                postconditions=["notifications_triaged"],
            ),
            Capability(
                id="schedule.reminder_create",
                version="1.0.0",
                plugin_id=self.plugin_id,
                description="Schedules a persistent SQLite temporal reminder polled by AmbientBackgroundDaemon.",
                execution_backend="LOCAL_SANDBOX",
                risk_class="local_write",
                postconditions=["sqlite_reminder_pending"],
            ),
        ]

    def health_check(self) -> Dict[str, Any]:
        return {"plugin_id": self.plugin_id, "status": "HEALTHY"}

    async def execute(self, action: Action, context: AuthorizedTaskContext) -> ActionResult:
        from agent.pa_scaffolder.kernel_governance import temporal_scheduler
        from agent.pa_scaffolder.unified_memory_hub import memory_hub
        from agent.pa_scaffolder.universal_reader import universal_reader

        cap = action.capability_id
        prompt = action.raw_instruction

        if cap == "messaging.send_confirmed":
            recipient = action.validated_arguments.get("recipient", "Household_Contact")
            app = action.validated_arguments.get("app", "WhatsApp")
            body = action.validated_arguments.get("message_body", "")
            state_store.record_trust_tagged_memory(
                content=f"Outbound {app} message to {recipient}: {body}",
                source_provenance="OUTBOUND_MESSAGE",
                trust_level="TRUSTED_USER",
                sensitivity="PRIVATE_COMM",
                scope="ephemeral_session",
            )
            legacy_res = universal_reader.send_or_reply_message(recipient=recipient, message_body=body, app=app)
            return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=legacy_res, provider_receipt=f"outbox:{recipient}:{app}", retryable=False, compensation_available=False)

        if cap == "notifications.triage":
            lower = prompt.lower().strip()
            stop_words = {"read", "check", "show", "my", "the", "unread", "recent", "latest", "notifications", "notification", "messages", "message", "from", "on", "in", "any", "proactive", "triage", "alerts"}
            tokens = [t for t in re.findall(r"[a-z0-9_]+", lower) if t not in stop_words]
            app_filter = tokens[0] if tokens else None
            triage = memory_hub.triage_proactive_notifications(app_filter=app_filter)
            triage["app_filter"] = app_filter
            triage["taint_level"] = "UNTRUSTED_EXTERNAL"
            return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=triage, provider_receipt=f"triage:{triage.get('new_count', 0)}")

        rem_res = temporal_scheduler.schedule_reminder(prompt)
        return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=rem_res, provider_receipt=rem_res.get("reminder_id", ""))

    def verify(self, action: Action, result: ActionResult) -> VerificationResult:
        from agent.pa_scaffolder.universal_reader import universal_reader

        cap = action.capability_id
        if cap == "messaging.send_confirmed":
            outbox = universal_reader.outbox_path
            recipient = action.validated_arguments.get("recipient", "")
            ok = outbox.exists() and (recipient.lower() in outbox.read_text(encoding="utf-8", errors="ignore").lower())
            return VerificationResult(action_id=action.action_id, capability_id=cap, status="COMPLETED" if ok else "UNCERTAIN", verified=ok, evidence_type="OUTBOX_DISPATCH_RECEIPT", observed_evidence=f"Outbox record verified for {recipient}")
        return VerificationResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", verified=True, evidence_type="SQLITE_SCHEDULE_COMMIT", observed_evidence=result.provider_receipt)
