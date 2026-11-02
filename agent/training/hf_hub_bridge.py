import os
import json
import time
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

try:
    from huggingface_hub import HfApi, hf_hub_download
    HAS_HF_NATIVE = True
except ImportError:
    HAS_HF_NATIVE = False


class HuggingFaceHubBridge:
    """
    Production Hugging Face Hub Client.
    Supports native HfApi with pure-requests fallback.
    Enables anonymous reads and authenticated swarm synchronization.
    """
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY", "")
        self.base_api = "https://huggingface.co/api"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "OSS-Agent-Collective-Hub/1.0"
        } if self.token else {"User-Agent": "OSS-Agent-Collective-Hub/1.0"}

        self.api = HfApi(token=self.token) if (HAS_HF_NATIVE and self.token) else (HfApi() if HAS_HF_NATIVE else None)

    def get_authenticated_user(self) -> Optional[str]:
        """Validates write token and returns active username."""
        if not self.token:
            return None

        if HAS_HF_NATIVE and self.api:
            try:
                info = self.api.whoami(token=self.token)
                return info.get("name")
            except Exception:
                pass

        try:
            res = requests.get(f"{self.base_api}/whoami-v2", headers=self.headers, timeout=10)
            if res.status_code == 200:
                return res.json().get("name")
        except Exception:
            pass
        return None

    def ensure_repository(self, repo_name: str, repo_type: str = "dataset", private: bool = False) -> Tuple[bool, str]:
        """Provisions target repository if not already present."""
        username = self.get_authenticated_user()
        if not username:
            return False, "Authentication required to create or write to repositories."

        full_repo_id = f"{username}/{repo_name}"

        if HAS_HF_NATIVE and self.api:
            try:
                self.api.create_repo(
                    repo_id=full_repo_id,
                    repo_type=repo_type,
                    private=private,
                    exist_ok=True
                )
                return True, f"Repository ready: {full_repo_id}"
            except Exception as e:
                return False, f"HfApi create error: {e}"

        # Fallback via direct REST
        try:
            res = requests.post(
                f"{self.base_api}/repos/create",
                headers=self.headers,
                json={"name": repo_name, "type": repo_type, "private": private},
                timeout=15
            )
            if res.status_code in (200, 201, 409):
                return True, f"Repository ready: {full_repo_id}"
            return False, f"HF API error ({res.status_code}): {res.text[:150]}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def upload_file(self, repo_id: str, local_path: Path, path_in_repo: str, repo_type: str = "dataset") -> Tuple[bool, str]:
        """Uploads a single artifact to the Hub."""
        if not self.token:
            return False, "Write token required for uploads."
        if not local_path.exists():
            return False, f"Local file not found: {local_path}"

        if HAS_HF_NATIVE and self.api:
            try:
                self.api.upload_file(
                    path_or_fileobj=str(local_path),
                    path_in_repo=path_in_repo,
                    repo_id=repo_id,
                    repo_type=repo_type,
                    commit_message=f"Sync {path_in_repo}"
                )
                return True, f"Committed {path_in_repo} to {repo_id}"
            except Exception as e:
                return False, f"Upload error: {e}"

        # Fallback via direct commit upload endpoint
        url = f"https://huggingface.co/api/{repo_type}s/{repo_id}/upload/main/{path_in_repo}"
        try:
            with open(local_path, "rb") as f:
                res = requests.post(url, headers=self.headers, data=f, timeout=60)
            if res.status_code in (200, 201):
                return True, f"Uploaded {path_in_repo} to {repo_id}"
            return False, f"Upload failed ({res.status_code}): {res.text[:150]}"
        except Exception as e:
            return False, f"Upload error: {e}"

    def download_json_file(self, repo_id: str, path_in_repo: str, repo_type: str = "dataset") -> Optional[Dict[str, Any]]:
        """
        Public, anonymous download for manifests and skill files.
        Requires zero tokens for public repositories.
        """
        raw_url = f"https://huggingface.co/datasets/{repo_id}/raw/main/{path_in_repo}" if repo_type == "dataset" else f"https://huggingface.co/{repo_id}/raw/main/{path_in_repo}"
        try:
            res = requests.get(raw_url, headers=self.headers, timeout=12)
            if res.status_code == 200:
                return res.json()
        except Exception:
            pass
        return None
