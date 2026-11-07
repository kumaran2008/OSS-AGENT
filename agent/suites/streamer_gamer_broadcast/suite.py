from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.pa_scaffolder.advanced_companion import AdvancedStreamCompanion
from agent.pa_scaffolder.vad_wakeword_engine import PurePythonVAD, WakeWordGatingFilter


@dataclass
class AudioRoutingDecision:
    destination_channel: str
    is_private_only: bool
    deterministic_secret_detected: bool
    jev_privacy_confidence: float
    reason: str


class StreamerGamerBroadcastSuite:
    """Section 7: Production Streamer & Gamer Suite with Live OS Telemetry & Dual-Audio Guard."""

    DETERMINISTIC_PRIVATE_PATTERNS = (
        r"\botp\b", r"\bverification\s+code\b", r"\b2fa\b", r"\b\d{6}\b",
        r"\bpassword\b", r"\bapi[_\s]?key\b", r"\bbank\b", r"\bcard\s+ending\b",
    )

    MODERATION_PERMISSION_POLICY = {
        "identify_spam": "AUTOMATIC",
        "hide_duplicate_spam": "AUTOMATIC_IF_AUTHORISED",
        "timeout_user": "CONFIGURABLE_AUTO",
        "permanent_ban": "HUMAN_APPROVAL_REQUIRED",
        "delete_moderator_message": "NEVER_AUTOMATIC",
    }

    def __init__(self):
        self.stream_companion = AdvancedStreamCompanion()
        self.wakeword_filter = WakeWordGatingFilter()
        self.vad_engine = PurePythonVAD()
        self.operating_mode = "COMPETITIVE_GAMING"
        self.background_indexing_throttled = True

    @staticmethod
    def read_live_host_ram_and_cpu() -> Dict[str, Any]:
        load_1m = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.5
        mem_total_mb = 4096.0
        mem_avail_mb = 2048.0
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            txt = meminfo.read_text(encoding="utf-8", errors="ignore")
            m_tot = re.search(r"MemTotal:\s+(\d+)\s+kB", txt)
            m_av = re.search(r"MemAvailable:\s+(\d+)\s+kB", txt)
            if m_tot:
                mem_total_mb = round(int(m_tot.group(1)) / 1024.0, 1)
            if m_av:
                mem_avail_mb = round(int(m_av.group(1)) / 1024.0, 1)
        return {
            "cpu_count": os.cpu_count() or 1,
            "load_avg_1m": round(load_1m, 2),
            "ram_total_mb": mem_total_mb,
            "ram_available_mb": mem_avail_mb,
        }

    def route_audio_safely(self, spoken_text: str, obs_captures_private_device: bool = False) -> AudioRoutingDecision:
        det_hit = any(re.search(pat, spoken_text, flags=re.IGNORECASE) for pat in self.DETERMINISTIC_PRIVATE_PATTERNS)
        q_priv = {
            "is_sensitive_or_personal": {
                "type": "noul",
                "affirmative_signals": ["otp", "code", "password", "secret", "bank", "address", "phone number", "private"],
                "prior_true": 0.15,
            }
        }
        jev_res = jev_ai_brain.evaluate_primitives(spoken_text, q_priv)["is_sensitive_or_personal"]
        is_private = det_hit or bool(jev_res.value) or obs_captures_private_device

        if is_private:
            return AudioRoutingDecision(
                destination_channel="PRIVATE_HEADPHONE_IEM",
                is_private_only=True,
                deterministic_secret_detected=det_hit,
                jev_privacy_confidence=jev_res.confidence,
                reason="Routed exclusively to Private Headphones/IEM (blocked from OBS Public Stream Mix).",
            )
        return AudioRoutingDecision(
            destination_channel="OBS_PUBLIC_MIX",
            is_private_only=False,
            deterministic_secret_detected=False,
            jev_privacy_confidence=jev_res.confidence,
            reason="Verified public-safe commentary; routed to OBS Stream Mix.",
        )

    def moderate_chat_with_permission_tiers(
        self,
        chat_messages: List[Dict[str, Any]],
        auto_hide_spam_authorised: bool = True,
        human_approved_bans: bool = False,
    ) -> Dict[str, Any]:
        seen_texts: Dict[str, int] = {}
        results: List[Dict[str, Any]] = []
        moderation_queue_for_human: List[Dict[str, Any]] = []

        for msg in chat_messages:
            user = str(msg.get("user", "viewer"))
            role = str(msg.get("role", "viewer")).lower()
            text = str(msg.get("message", ""))
            norm_text = text.strip().lower()
            seen_texts[norm_text] = seen_texts.get(norm_text, 0) + 1

            if role in ("moderator", "mod", "broadcaster", "streamer"):
                results.append({
                    "user": user,
                    "role": role,
                    "executed_action": "ALLOW_PROTECTED_MODERATOR",
                    "policy_enforced": self.MODERATION_PERMISSION_POLICY["delete_moderator_message"],
                })
                continue

            batch_eval = jev_ai_brain.moderate_streamer_live_chat_batch([{"user": user, "message": text}])
            raw_act = batch_eval["decisions"][0]["mod_action"]
            tox_score = batch_eval["decisions"][0]["toxicity_score"]
            conf = batch_eval["decisions"][0]["confidence"]

            if seen_texts[norm_text] >= 2 and auto_hide_spam_authorised:
                exec_act = "HIDE_DUPLICATE_SPAM"
            elif raw_act == "delete_spam":
                exec_act = "HIDE_SPAM_AUTOMATIC" if auto_hide_spam_authorised else "FLAGGED_SPAM"
            elif raw_act == "timeout_600s":
                if tox_score >= 0.85 and not human_approved_bans:
                    exec_act = "TIMEOUT_600S_AND_QUEUED_FOR_HUMAN_BAN_REVIEW"
                    moderation_queue_for_human.append({"user": user, "message": text, "confidence": conf})
                elif human_approved_bans:
                    exec_act = "PERMANENT_BAN_APPROVED"
                else:
                    exec_act = "TIMEOUT_600S"
            else:
                exec_act = raw_act.upper()

            results.append({"user": user, "role": role, "executed_action": exec_act, "confidence": conf})

        return {
            "processed_count": len(results),
            "decisions": results,
            "human_ban_approval_queue": moderation_queue_for_human,
        }

    def evaluate_background_notification_during_gaming(self, sender: str, message_text: str) -> Dict[str, Any]:
        q_urg = {
            "real_world_consequence": {
                "type": "score",
                "levels": [1, 2, 3, 4, 5],
                "high_signals": ["locked outside", "battery at 2%", "hospital", "emergency", "server crashed", "security breach", "flight", "keys"],
                "mid_signals": ["call me", "meeting"],
            },
            "is_genuine_emergency": {
                "type": "noul",
                "affirmative_signals": ["locked outside", "battery", "hospital", "emergency", "breach", "keys"],
                "negative_signals": ["meme", "reel", "funny", "watch this"],
            },
        }
        prims = jev_ai_brain.evaluate_primitives(message_text, q_urg)
        interrupt_player = bool(prims["is_genuine_emergency"].value) and prims["real_world_consequence"].value >= 0.65
        return {
            "sender": sender,
            "interrupt_gameplay_headset": interrupt_player,
            "consequence_score": prims["real_world_consequence"].value,
            "delivery_action": "WHISPER_TO_HEADSET" if interrupt_player else "SILENTLY_QUEUED_UNTIL_MATCH_ENDS",
        }

    def monitor_gaming_performance_and_highlights(
        self,
        fps: float = 144.0,
        one_percent_low_fps: float = 128.0,
        frame_time_ms: float = 6.9,
        audio_db_spike: float = 88.0,
        chat_msgs_per_10s: int = 45,
    ) -> Dict[str, Any]:
        hw = self.read_live_host_ram_and_cpu()
        is_highlight = (audio_db_spike >= 80.0 and chat_msgs_per_10s >= 25)
        return {
            "fps": fps,
            "one_percent_low_fps": one_percent_low_fps,
            "frame_time_ms": frame_time_ms,
            "system_load_1m": hw["load_avg_1m"],
            "ram_available_mb": hw["ram_available_mb"],
            "friday_background_tasks_throttled": self.background_indexing_throttled,
            "external_processes_terminated": 0,
            "highlight_detected": is_highlight,
            "replay_buffer_action": "SAVED_CLIP_MARKER" if is_highlight else "MONITORING",
            "suggested_clip_title": f"High-Energy Clutch Moment ({int(fps)} FPS)" if is_highlight else None,
        }



    def check_dead_air_and_banter(self, event_type: str = 'clutch', chat_lines: list = None) -> Dict[str, Any]:
        '''Integrates FILE 14 (StreamInteractionDirector) for dead-air hooks and brotherly banter.'''
        from agent.core.stream_director import StreamInteractionDirector
        director = getattr(self, '_interaction_director', None)
        if director is None:
            director = StreamInteractionDirector(cohost_name='Friday')
            self._interaction_director = director
        for msg in (chat_lines or []):
            director.ingest_chat_message(msg.get('user', 'viewer'), msg.get('message', ''))
        vibe = director.aggregate_chat_vibe()
        banter = director.craft_brother_banter(event_type)
        return {'vibe': vibe, 'banter': banter, 'dead_air_check': director.check_dead_air()}

streamer_gamer_suite = StreamerGamerBroadcastSuite()
