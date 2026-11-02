import os
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional


@dataclass
class PrivacyLockState:
    is_locked: bool = False
    shutdown_initiated_at: float = 0.0
    duration_seconds: float = 0.0
    reason: str = ""
    resumed_manually: bool = False


class EmergencyPrivacyGuard:
    """
    Enforces immediate cessation of all PA sensory listeners (mic, screen, tools)
    when the user commands an emergency privacy shutdown.
    """
    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or (Path.home() / ".personal_agent" / "memory")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.storage_dir / "privacy_lock.json"
        self._state = self._load_state()

    def _load_state(self) -> PrivacyLockState:
        if self.lock_file.exists():
            try:
                with open(self.lock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return PrivacyLockState(**data)
            except Exception:
                pass
        return PrivacyLockState()

    def _save_state(self):
        with open(self.lock_file, "w", encoding="utf-8") as f:
            json.dump(self._state.__dict__, f, indent=2)

    def trigger_shutdown(self, hours: float = 24.0, reason: str = "User Emergency Privacy Directive") -> Dict[str, Any]:
        """
        Immediately locks down the agent and disables listeners for specified hours.
        """
        duration_sec = float(hours * 3600.0)
        now = time.time()
        self._state = PrivacyLockState(
            is_locked=True,
            shutdown_initiated_at=now,
            duration_seconds=duration_sec,
            reason=reason,
            resumed_manually=False
        )
        self._save_state()
        return {
            "status": "SHUTDOWN_ACTIVE",
            "shutdown_hours": hours,
            "locked_until_epoch": now + duration_sec,
            "action": "All camera, microphone, clipboard, and screen listeners revoked."
        }

    def check_lock_status(self) -> Tuple[bool, str]:
        """
        Returns (is_active_lock, status_message).
        Automatically clears lock once time window expires.
        """
        if not self._state.is_locked:
            return False, "Agent is online and unrestricted."

        now = time.time()
        elapsed = now - self._state.shutdown_initiated_at
        remaining = self._state.duration_seconds - elapsed

        if remaining <= 0:
            # Automatic expiration
            self._state.is_locked = False
            self._save_state()
            return False, "Privacy shutdown window has expired. Agent is ready to awaken."

        remaining_hrs = remaining / 3600.0
        return True, f"EMERGENCY PRIVACY LOCK ACTIVE ({remaining_hrs:.2f} hours remaining). All processing blocked."

    def manual_override_unlock(self) -> Tuple[bool, str]:
        """Allows manual reactivation before timer expiration."""
        self._state.is_locked = False
        self._state.resumed_manually = True
        self._save_state()
        return True, "Privacy lock manually revoked by operator. Systems restored."
