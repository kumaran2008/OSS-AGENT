from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.pa_scaffolder.secure_vault import vault


class GitHubBridge:
    """Production Automated GitHub Provisioner.
    - Automatically discovers existing tokens or drives CDP token generation.
    - Initializes local git repositories, creates remote repos, and pushes code.
    """

    API_BASE = "https://api.github.com"

    def __init__(self):
        self._token: Optional[str] = None
        self._username: Optional[str] = None
        self.auto_connect()

    def auto_connect(self) -> Tuple[bool, Optional[str]]:
        # 1. Environment
        env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if env_token:
            ok, user = self._verify_token(env_token.strip())
            if ok:
                self._token = env_token.strip()
                self._username = user
                vault.store_key("github", self._token)
                return True, user

        # 2. Vault DB
        vault_token = vault.get_key("github")
        if vault_token:
            ok, user = self._verify_token(vault_token.strip())
            if ok:
                self._token = vault_token.strip()
                self._username = user
                os.environ["GITHUB_TOKEN"] = self._token
                return True, user

        # 3. gh CLI Active Session Extraction
        if shutil.which("gh"):
            try:
                out = subprocess.check_output(["gh", "auth", "token"], timeout=2.0)
                extracted = out.decode("utf-8").strip()
                if extracted and not extracted.startswith("no token"):
                    ok, user = self._verify_token(extracted)
                    if ok:
                        self._token = extracted
                        self._username = user
                        os.environ["GITHUB_TOKEN"] = extracted
                        vault.store_key("github", extracted)
                        return True, user
            except Exception:
                pass

        return False, None

    def _verify_token(self, token: str) -> Tuple[bool, Optional[str]]:
        req = urllib.request.Request(
            f"{self.API_BASE}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "oss-agent/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return True, data.get("login")
        except Exception:
            return False, None

    def get_status(self) -> Dict[str, Any]:
        if not self._token:
            self.auto_connect()
        return {
            "connected": bool(self._token and self._username),
            "username": self._username,
            "has_gh_cli": bool(shutil.which("gh")),
        }

    def setup_and_publish_repo(self, repo_name: Optional[str] = None, private: bool = True) -> Dict[str, Any]:
        """Completely initializes Git, creates remote GitHub repo, and pushes initial commit."""
        connected, user = self.auto_connect()
        if not connected:
            return {
                "success": False,
                "error": "GitHub is not connected. Authenticate with 'gh auth login' or save your token in vault.",
            }

        curr_dir = Path(".").resolve()
        name = repo_name or curr_dir.name

        # 1. Initialize local Git if missing
        try:
            if not (curr_dir / ".git").exists():
                subprocess.run(["git", "init"], check=True, capture_output=True)
                subprocess.run(["git", "checkout", "-b", "main"], check=False, capture_output=True)

            # Ensure minimal gitignore
            gi = curr_dir / ".gitignore"
            if not gi.exists():
                gi.write_text("venv/\n__pycache__/\nworkspace/vault.db\n.env\n*.png\n", encoding="utf-8")

            subprocess.run(["git", "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial commit from OSS Agent"], check=False, capture_output=True)

            # 2. Create remote repo via REST API
            req_data = json.dumps({"name": name, "private": private, "auto_init": False}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.API_BASE}/user/repos",
                data=req_data,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "oss-agent/1.0",
                },
                method="POST",
            )
            remote_url = ""
            try:
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    remote_url = resp_data.get("clone_url")
            except urllib.error.HTTPError as e:
                if e.code == 422:  # Already exists
                    remote_url = f"https://github.com/{user}/{name}.git"
                else:
                    return {"success": False, "error": f"Failed to create remote repository: {e}"}

            # 3. Add remote origin and push
            subprocess.run(["git", "remote", "remove", "origin"], check=False, capture_output=True)
            auth_remote = remote_url.replace("https://", f"https://{self._token}@")
            subprocess.run(["git", "remote", "add", "origin", auth_remote], check=True, capture_output=True)
            push_res = subprocess.run(["git", "push", "-u", "origin", "main"], capture_output=True, text=True)

            # Clean token out of remote origin URL for security
            subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=False, capture_output=True)

            return {
                "success": True,
                "repo_name": name,
                "remote_url": remote_url,
                "user": user,
                "push_output": push_res.stdout or "Push complete.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


github_automator = GitHubBridge()
