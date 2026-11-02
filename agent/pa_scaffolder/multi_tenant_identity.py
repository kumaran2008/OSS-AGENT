import json
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


class Role(str, Enum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    GUEST = "guest"


@dataclass
class UserProfile:
    user_id: str
    display_name: str
    role: Role
    preferred_voice: str = "am_adam"
    custom_instructions: str = ""
    preferences: Dict[str, Any] = field(default_factory=dict)


class MultiTenantIdentityManager:
    """
    Multi-Person User Identity, Memory Partitioning, and Permission Gatekeeper.
    Maintains tenant-isolated preference graphs and Role-Based Access Control (RBAC).
    """

    PROFILES_PATH = Path("workspace/profiles.json")

    DEFAULT_PROFILES = {
        "admin": UserProfile(
            user_id="admin",
            display_name="Tony",
            role=Role.ADMIN,
            preferred_voice="am_adam",
            custom_instructions="Witty, high-speed engineering partner.",
            preferences={"editor": "neovim", "auto_patch": True}
        ),
        "dev": UserProfile(
            user_id="dev",
            display_name="Alex",
            role=Role.DEVELOPER,
            preferred_voice="am_echo",
            custom_instructions="Concise technical answers only.",
            preferences={"editor": "vscode", "auto_patch": False}
        ),
        "guest": UserProfile(
            user_id="guest",
            display_name="Guest",
            role=Role.GUEST,
            preferred_voice="af_heart",
            custom_instructions="Polite conversational guide.",
            preferences={"restricted": True}
        )
    }

    def __init__(self):
        self.PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.profiles: Dict[str, UserProfile] = {}
        self.active_user_id: str = "admin"
        self._load_or_bootstrap()

    def _load_or_bootstrap(self):
        if self.PROFILES_PATH.exists():
            try:
                data = json.loads(self.PROFILES_PATH.read_text(encoding="utf-8"))
                for uid, p in data.items():
                    self.profiles[uid] = UserProfile(
                        user_id=p["user_id"],
                        display_name=p["display_name"],
                        role=Role(p["role"]),
                        preferred_voice=p.get("preferred_voice", "am_adam"),
                        custom_instructions=p.get("custom_instructions", ""),
                        preferences=p.get("preferences", {})
                    )
                self.active_user_id = data.get("_active_user", "admin")
                return
            except Exception:
                pass

        # Seed defaults
        self.profiles = dict(self.DEFAULT_PROFILES)
        self.active_user_id = "admin"
        self._save()

    def _save(self):
        dump = {uid: {
            "user_id": p.user_id,
            "display_name": p.display_name,
            "role": p.role.value,
            "preferred_voice": p.preferred_voice,
            "custom_instructions": p.custom_instructions,
            "preferences": p.preferences
        } for uid, p in self.profiles.items()}
        dump["_active_user"] = self.active_user_id
        self.PROFILES_PATH.write_text(json.dumps(dump, indent=2), encoding="utf-8")

    @property
    def current_user(self) -> UserProfile:
        return self.profiles.get(self.active_user_id, self.DEFAULT_PROFILES["admin"])

    def switch_user(self, identifier: str) -> Tuple[bool, str]:
        """Switches active tenant profile by user_id or display_name."""
        clean = identifier.lower().strip()
        for uid, prof in self.profiles.items():
            if uid.lower() == clean or prof.display_name.lower() == clean:
                self.active_user_id = uid
                self._save()
                return True, f"Identity switched to {prof.display_name} (Role: {prof.role.value.capitalize()})."

        return False, f"User profile matching '{identifier}' not found."

    def authorize_tool_action(self, tool_name: str) -> Tuple[bool, Optional[str]]:
        """
        Enforces Role-Based Access Control on tool execution.
        """
        role = self.current_user.role

        # Admin: unconstrained access
        if role == Role.ADMIN:
            return True, None

        # Developer: code reading/writing allowed, arbitrary terminal commands restricted
        if role == Role.DEVELOPER:
            if tool_name in ["bash_execute", "window_focus"]:
                return True, None
            if tool_name in ["file_read", "file_write", "file_patch"]:
                return True, None
            return False, f"Action '{tool_name}' requires Admin privileges."

        # Guest: read-only queries only
        if role == Role.GUEST:
            if tool_name in ["file_read"]:
                return True, None
            return False, f"Permission Denied: User '{self.current_user.display_name}' has Guest status."

        return False, "Unknown role permissions."

    def get_scoped_tenant_prefix(self) -> str:
        """Returns tenant key used for isolated memory partition queries."""
        return f"tenant_{self.active_user_id}_"
