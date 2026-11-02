import os
import re
import urllib.request
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional


class DynamicAuthManager:
    """
    Manages dynamic in-flight API keys and GitHub tokens.
    Validates tokens live and hot-reloads them into memory and .env.
    """
    def __init__(self, env_path: Optional[Path] = None):
        self.env_path = env_path or (Path.cwd() / ".env")

    def test_openrouter_key(self, api_key: str) -> Tuple[bool, str]:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "OSS-Agent"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                label = data.get("data", {}).get("label", "Active Key")
                limit_remaining = data.get("data", {}).get("limit_remaining", "Unlimited")
                return True, f"OpenRouter Key verified ({label}, Credits: ${limit_remaining})"
        except Exception as e:
            return False, f"Invalid OpenRouter Key: {e}"

    def test_github_token(self, token: str) -> Tuple[bool, str]:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}", "User-Agent": "OSS-Agent"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                user = data.get("login", "Authenticated")
                return True, f"GitHub token valid for user: @{user}"
        except Exception as e:
            return False, f"Invalid GitHub token: {e}"

    def test_groq_key(self, api_key: str) -> Tuple[bool, str]:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "OSS-Agent"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return True, "Groq Ultra-Fast API Key verified."
        except Exception as e:
            return False, f"Invalid Groq Key: {e}"

    def update_key(self, key_name: str, key_value: str) -> Tuple[bool, str]:
        """Validates key, hot-loads into os.environ, and updates .env file."""
        key_value = key_value.strip()
        is_valid = True
        status_msg = "Updated"

        if key_name == "OPENROUTER_API_KEY":
            is_valid, status_msg = self.test_openrouter_key(key_value)
        elif key_name == "GITHUB_TOKEN":
            is_valid, status_msg = self.test_github_token(key_value)
        elif key_name == "GROQ_API_KEY":
            is_valid, status_msg = self.test_groq_key(key_value)

        if not is_valid:
            return False, status_msg

        # Hot-reload in memory
        os.environ[key_name] = key_value

        # Persist to .env
        lines = []
        if self.env_path.exists():
            with open(self.env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key_name}="):
                new_lines.append(f"{key_name}={key_value}\n")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key_name}={key_value}\n")

        with open(self.env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"[✓] {status_msg} and saved to .env."

    def detect_missing_credentials(self) -> Dict[str, bool]:
        """Returns dict of which credentials are missing or empty."""
        return {
            "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
            "GITHUB_TOKEN": bool(os.environ.get("GITHUB_TOKEN")),
            "GROQ_API_KEY": bool(os.environ.get("GROQ_API_KEY")),
            "HUGGINGFACE_TOKEN": bool(os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY"))
        }

auth_manager = DynamicAuthManager()
