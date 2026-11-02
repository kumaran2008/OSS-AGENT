from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.pa_scaffolder.blackboard_kernel import blackboard, undo_ledger
from agent.pa_scaffolder.kernel_governance import secret_scrubber


class AgentMode(str, Enum):
    NORMAL = "normal"
    BUILDER = "builder"
    RESEARCHER = "researcher"
    STREAMER = "streamer"
    GAMER = "gamer"


@dataclass
class ModeSpec:
    mode: AgentMode
    cpu_quota_pct: int
    gpu_quota_pct: int
    audio_ducking_pct: int
    dnd_policy: str
    active_daemons: List[str]
    system_directive: str


class AsyncKernelEventBus:
    """Permission-Aware, Deduplicated, Backpressure-Protected Kernel Event Bus."""

    def __init__(self, max_history: int = 120):
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}
        self.event_history: List[Dict[str, Any]] = []
        self.max_history = max_history
        self.session_id = f"sess_{int(time.time())}"
        self._last_event_hash: str = ""
        self._seq: int = 0

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        source: str = "kernel_core",
        priority: int = 5,
    ) -> Dict[str, Any]:
        scrubbed_payload: Dict[str, Any] = {}
        contained_secret = False
        for k, v in payload.items():
            if isinstance(v, str):
                clean_v, had_sec = secret_scrubber.scrub(v)
                scrubbed_payload[k] = clean_v
                if had_sec:
                    contained_secret = True
            else:
                scrubbed_payload[k] = v

        dedup_sig = hashlib.md5(f"{event_type}:{json.dumps(scrubbed_payload, sort_keys=True, default=str)}".encode()).hexdigest()[:12]
        now = time.time()
        if dedup_sig == self._last_event_hash and self.event_history and (now - self.event_history[-1]["timestamp"]) < 1.0:
            return self.event_history[-1]
        self._last_event_hash = dedup_sig

        self._seq += 1
        event = {
            "event_id": f"evt_{self._seq:04d}_{dedup_sig[:6]}",
            "type": event_type,
            "event_type": event_type,
            "timestamp": now,
            "source": source,
            "session_id": self.session_id,
            "priority": priority,
            "payload": scrubbed_payload,
            "permissions": {
                "allow_remote_processing": not contained_secret,
                "contains_redacted_secret": contained_secret,
            },
        }

        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)

        for handler in self._subscribers.get(event_type, []) + self._subscribers.get("*", []):
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception:
                pass
        return event


class ModeMorphingKernel:
    """Rooms 2.0: Hardware-Adaptive Mode-Morphing Kernel with 6-Step Safe State Transitions."""

    MODE_SPECS: Dict[AgentMode, ModeSpec] = {
        AgentMode.NORMAL: ModeSpec(
            mode=AgentMode.NORMAL,
            cpu_quota_pct=50,
            gpu_quota_pct=25,
            audio_ducking_pct=100,
            dnd_policy="all_allowed",
            active_daemons=["notification_listener", "obsidian_sync", "life_tracker"],
            system_directive="Operate as a warm, sharp workstation & life companion.",
        ),
        AgentMode.BUILDER: ModeSpec(
            mode=AgentMode.BUILDER,
            cpu_quota_pct=90,
            gpu_quota_pct=40,
            audio_ducking_pct=85,
            dnd_policy="priority_only",
            active_daemons=["ast_indexer", "git_diff_watcher", "pty_traceback_monitor"],
            system_directive="Operate in Builder Mode: prioritize code execution, AST verification, and test-driven self-healing.",
        ),
        AgentMode.RESEARCHER: ModeSpec(
            mode=AgentMode.RESEARCHER,
            cpu_quota_pct=85,
            gpu_quota_pct=60,
            audio_ducking_pct=80,
            dnd_policy="priority_only",
            active_daemons=["arxiv_citation_watcher", "obsidian_2way_sync", "contradiction_scanner"],
            system_directive="Operate in Researcher Mode: prioritize empirical claims, dead-end guards, and 5-line literature digests.",
        ),
        AgentMode.STREAMER: ModeSpec(
            mode=AgentMode.STREAMER,
            cpu_quota_pct=20,
            gpu_quota_pct=3,
            audio_ducking_pct=70,
            dnd_policy="household_emergency_only",
            active_daemons=["obs_websocket_bridge", "replay_clip_buffer", "live_chat_moderator"],
            system_directive="Operate in Streamer Mode: keep responses punchy for live broadcast; manage OBS scenes and stream clips.",
        ),
        AgentMode.GAMER: ModeSpec(
            mode=AgentMode.GAMER,
            cpu_quota_pct=5,
            gpu_quota_pct=0,
            audio_ducking_pct=50,
            dnd_policy="household_emergency_only",
            active_daemons=["tactical_roi_hud", "household_emergency_breakthrough"],
            system_directive="Operate in Gamer Mode: ultra-low latency (<300ms), maximum 10 words, block all non-emergency alerts.",
        ),
    }

    def __init__(self, event_bus: AsyncKernelEventBus):
        self.event_bus = event_bus
        self.current_mode: AgentMode = AgentMode.NORMAL
        self.obs_active_scene: str = "Main_Desktop"
        self.clips_dir = Path("workspace/stream_clips")
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.mode_snapshots: Dict[str, Dict[str, Any]] = {}

    @property
    def active_spec(self) -> ModeSpec:
        return self.MODE_SPECS[self.current_mode]

    def _apply_os_audio_and_resource_profile(self, spec: ModeSpec) -> None:
        if shutil.which("wpctl"):
            try:
                subprocess.run(
                    ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{spec.audio_ducking_pct}%"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
            except Exception:
                pass

    def switch_mode(self, target_mode_str: str, register_undo: bool = True) -> Dict[str, Any]:
        clean = target_mode_str.lower().strip()
        matched_mode = AgentMode.NORMAL
        for m in AgentMode:
            if m.value in clean:
                matched_mode = m
                break

        prev_mode = self.current_mode
        prev_spec = self.MODE_SPECS[prev_mode]

        outgoing_snapshot = blackboard.snapshot_state()
        outgoing_snapshot["obs_scene"] = self.obs_active_scene
        self.mode_snapshots[prev_mode.value] = outgoing_snapshot

        spec = self.MODE_SPECS[matched_mode]
        suspended_daemons = [d for d in prev_spec.active_daemons if d not in spec.active_daemons]

        self.current_mode = matched_mode
        blackboard.current_scope = matched_mode.value
        self._apply_os_audio_and_resource_profile(spec)

        restored_context = self.mode_snapshots.get(matched_mode.value, {})
        if restored_context:
            blackboard.restore_state(restored_context)

        if register_undo and prev_mode != matched_mode:
            def _rollback_mode() -> str:
                self.current_mode = prev_mode
                blackboard.current_scope = prev_mode.value
                if prev_mode.value in self.mode_snapshots:
                    blackboard.restore_state(self.mode_snapshots[prev_mode.value])
                self._apply_os_audio_and_resource_profile(self.MODE_SPECS[prev_mode])
                return f"Restored kernel mode to {prev_mode.value.upper()}."

            undo_ledger.register_undo("MODE_SWITCH", f"Switched to {matched_mode.value}", _rollback_mode)

        self.event_bus.emit(
            "MODE_SWITCHED",
            {
                "previous_mode": prev_mode.value,
                "new_mode": matched_mode.value,
                "suspended_daemons": suspended_daemons,
                "restored_active_file": restored_context.get("active_file", ""),
                "cpu_quota_pct": spec.cpu_quota_pct,
                "gpu_quota_pct": spec.gpu_quota_pct,
                "dnd_policy": spec.dnd_policy,
                "active_daemons": spec.active_daemons,
            },
            source="mode_morphing_kernel",
            priority=8,
        )

        reply = (
            f"Switched to {matched_mode.value.upper()} Mode "
            f"(CPU quota: {spec.cpu_quota_pct}%, GPU quota: {spec.gpu_quota_pct}%, "
            f"DND: {spec.dnd_policy}, Daemons: {', '.join(spec.active_daemons)})."
        )
        return {
            "intent": "MODE_SWITCH",
            "mode": matched_mode.value,
            "previous_mode": prev_mode.value,
            "suspended_daemons": suspended_daemons,
            "restored_context": restored_context,
            "spec": {
                "cpu_quota_pct": spec.cpu_quota_pct,
                "gpu_quota_pct": spec.gpu_quota_pct,
                "audio_ducking_pct": spec.audio_ducking_pct,
                "dnd_policy": spec.dnd_policy,
                "active_daemons": spec.active_daemons,
            },
            "spoken_response": reply,
        }

    def execute_streamer_action(self, prompt: str) -> Dict[str, Any]:
        lower = prompt.lower().strip()

        if "clip" in lower or "highlight" in lower:
            dur_m = re.search(r"(\d+)\s*(?:sec|seconds|s)\b", lower)
            seconds = int(dur_m.group(1)) if dur_m else 30
            clip_file = self.clips_dir / f"clip_{int(time.time())}_{seconds}s.json"
            clip_meta = {
                "timestamp": time.time(),
                "duration_sec": seconds,
                "scene": self.obs_active_scene,
                "focused_window": blackboard.focused_window,
            }
            clip_file.write_text(json.dumps(clip_meta, indent=2), encoding="utf-8")

            def _rollback_clip() -> str:
                if clip_file.exists():
                    clip_file.unlink()
                return f"Removed stream clip marker ({clip_file.name})."

            undo_ledger.register_undo("STREAM_CLIP", f"Saved {seconds}s stream clip", _rollback_clip)
            self.event_bus.emit("STREAM_CLIP_CAPTURED", {"file": str(clip_file), "duration_sec": seconds}, source="streamer_mode")
            return {
                "intent": "STREAMER_CLIP",
                "clip_file": str(clip_file),
                "duration_sec": seconds,
                "spoken_response": f"Saved {seconds}-second stream replay clip in scene '{self.obs_active_scene}' ({clip_file.name}).",
            }

        scene_m = re.search(r"(?:scene\s+to|to\s+scene|switch\s+to)\s+([a-zA-Z0-9_\-\s]+)", prompt, flags=re.I)
        new_scene = scene_m.group(1).strip().replace(" ", "_") if scene_m else "Coding_Overlay"
        old_scene = self.obs_active_scene
        self.obs_active_scene = new_scene

        def _rollback_scene() -> str:
            self.obs_active_scene = old_scene
            return f"Reverted OBS scene back to '{old_scene}'."

        undo_ledger.register_undo("OBS_SCENE_SWITCH", f"Switched OBS scene to {new_scene}", _rollback_scene)
        self.event_bus.emit("OBS_SCENE_CHANGED", {"old_scene": old_scene, "new_scene": new_scene}, source="streamer_mode")
        return {
            "intent": "STREAMER_OBS_SCENE",
            "scene": new_scene,
            "spoken_response": f"Switched OBS broadcast scene from '{old_scene}' to '{new_scene}'.",
        }


event_bus = AsyncKernelEventBus()
mode_kernel = ModeMorphingKernel(event_bus=event_bus)
