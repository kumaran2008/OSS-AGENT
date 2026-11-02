import os
import json
import time
import hashlib
import sqlite3
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

from agent.training.hf_hub_bridge import HuggingFaceHubBridge


@dataclass
class SkillBundle:
    skill_name: str
    description: str
    trigger_intents: List[str]
    entrypoint_code: str
    required_packages: List[str]
    parameters_schema: Dict[str, Any]
    author_node: str
    version: str = "1.0.0"


class CentralDatabaseConnector:
    """
    Production Federation Connector for Collective Swarm Intelligence.
    Handles bug patches, learned executable skills, and atomic Hub synchronization.
    """
    DEFAULT_COMMUNITY_REPO = os.getenv("HF_COMMUNITY_REPO", "aegis-collective/oss-agent-collective-data")

    def __init__(self, workspace_root: Optional[Path] = None, token: Optional[str] = None):
        self.workspace_root = workspace_root or Path.cwd()
        self.token = token or os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY", "")
        self.bridge = HuggingFaceHubBridge(token=self.token)
        self.db_path = self.workspace_root / ".codex" / "sync_queue.db"
        self._init_local_queue()

    def _init_local_queue(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Handle migration from previous table schema if present
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='outbound_queue'")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(outbound_queue)")
            cols = [row[1] for row in cur.fetchall()]
            if "identifier" not in cols and "signature" in cols:
                try:
                    cur.execute("ALTER TABLE outbound_queue RENAME COLUMN signature TO identifier")
                except Exception:
                    cur.execute("DROP TABLE outbound_queue")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS outbound_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT, -- 'patch' | 'skill' | 'trajectory'
                identifier TEXT UNIQUE,
                payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                synced INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def sanitize_payload(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Strips local system paths and sensitive API tokens."""
        clean_str = json.dumps(raw_data)
        home_dir = str(Path.home())
        clean_str = clean_str.replace(home_dir, "~")
        clean_str = clean_str.replace("/data/data/com.termux/files/home", "~")

        for env_key in ["OPENROUTER_API_KEY", "GITHUB_TOKEN", "HUGGINGFACE_TOKEN"]:
            val = os.environ.get(env_key)
            if val and len(val) > 6:
                clean_str = clean_str.replace(val, "[REDACTED_SECRET]")

        return json.loads(clean_str)

    # -------------------------------------------------------------
    # Staging Methods
    # -------------------------------------------------------------
    def stage_verified_patch(self, error_signature: str, resolution_logic: str, files_modified: List[str]) -> bool:
        """Enqueues a verified code/system patch."""
        payload = {
            "error_signature": error_signature,
            "resolution_logic": resolution_logic,
            "files_modified": files_modified,
            "timestamp": time.time()
        }
        sanitized = self.sanitize_payload(payload)
        return self._enqueue("patch", error_signature, sanitized)

    def stage_skill(self, skill: SkillBundle) -> bool:
        """Enqueues a learned agent capability or automation workflow."""
        sanitized = self.sanitize_payload(asdict(skill))
        return self._enqueue("skill", skill.skill_name, sanitized)

    def _enqueue(self, item_type: str, identifier: str, payload: Dict[str, Any]) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT OR REPLACE INTO outbound_queue (item_type, identifier, payload, synced)
                VALUES (?, ?, ?, 0)
            """, (item_type, identifier, json.dumps(payload)))
            conn.commit()
            return True
        except Exception as e:
            print(f"[Sync Queue Error]: {e}")
            return False
        finally:
            conn.close()

    # -------------------------------------------------------------
    # Hub Synchronization
    # -------------------------------------------------------------
    def sync_to_central_hub(self, repo_name: str = "oss-agent-collective-data") -> Dict[str, Any]:
        """
        Merges queued local entries with remote repository data
        and commits atomic artifacts to the Hugging Face Hub.
        """
        username = self.bridge.get_authenticated_user()
        if not username:
            return {"status": "OFFLINE", "message": "No HUGGINGFACE_TOKEN configured. Artifacts queued locally."}

        full_repo = f"{username}/{repo_name}"
        self.bridge.ensure_repository(repo_name, repo_type="dataset", private=False)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, item_type, identifier, payload FROM outbound_queue WHERE synced = 0")
        rows = cur.fetchall()

        if not rows:
            conn.close()
            return {"status": "UP_TO_DATE", "message": "Queue empty. All items synced."}

        # Step 1: Download current manifests to prevent overwrite collisions
        patches_manifest = self.bridge.download_json_file(full_repo, "patches/patches_manifest.json") or {}
        skills_manifest = self.bridge.download_json_file(full_repo, "skills/skills_manifest.json") or {}

        staged_dir = self.workspace_root / ".codex" / "staging"
        staged_dir.mkdir(parents=True, exist_ok=True)
        synced_ids = []

        # Step 2: Merge entries and write atomic files
        for row_id, item_type, identifier, payload_str in rows:
            data = json.loads(payload_str)

            if item_type == "patch":
                sig_hash = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
                patches_manifest[identifier] = data
                patch_file = staged_dir / f"patch_{sig_hash}.json"
                with open(patch_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                self.bridge.upload_file(full_repo, patch_file, f"patches/entries/patch_{sig_hash}.json")

            elif item_type == "skill":
                skills_manifest[identifier] = data
                skill_file = staged_dir / f"skill_{identifier}.json"
                with open(skill_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                self.bridge.upload_file(full_repo, skill_file, f"skills/entries/skill_{identifier}.json")

            synced_ids.append(row_id)

        # Step 3: Commit updated merged manifests
        merged_patches_file = staged_dir / "patches_manifest.json"
        with open(merged_patches_file, "w", encoding="utf-8") as f:
            json.dump(patches_manifest, f, indent=2)
        self.bridge.upload_file(full_repo, merged_patches_file, "patches/patches_manifest.json")

        merged_skills_file = staged_dir / "skills_manifest.json"
        with open(merged_skills_file, "w", encoding="utf-8") as f:
            json.dump(skills_manifest, f, indent=2)
        self.bridge.upload_file(full_repo, merged_skills_file, "skills/skills_manifest.json")

        # Step 4: Mark items synced in local database
        for sid in synced_ids:
            cur.execute("UPDATE outbound_queue SET synced = 1 WHERE id = ?", (sid,))
        conn.commit()
        conn.close()

        return {
            "status": "SUCCESS",
            "repo": full_repo,
            "items_synced": len(synced_ids),
            "total_patches": len(patches_manifest),
            "total_skills": len(skills_manifest)
        }

    # -------------------------------------------------------------
    # Swarm Retrieval (Local Queue First + Anonymous Remote Fallback)
    # -------------------------------------------------------------
    def fetch_community_patches(self, repo_id: Optional[str] = None) -> Dict[str, Any]:
        target = repo_id or self._resolve_read_target()
        data = self.bridge.download_json_file(target, "patches/patches_manifest.json")
        return data or {}

    def fetch_community_skills(self, repo_id: Optional[str] = None) -> Dict[str, Any]:
        target = repo_id or self._resolve_read_target()
        data = self.bridge.download_json_file(target, "skills/skills_manifest.json")
        return data or {}

    def find_skill_by_intent(self, user_intent: str) -> Optional[Dict[str, Any]]:
        """
        Resolves intent to a skill bundle.
        Checks locally staged/synced skills first (offline ready), then queries the Hub.
        """
        intent_lower = user_intent.lower()

        # 1. Local-first search
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT payload FROM outbound_queue WHERE item_type = 'skill'")
            rows = cur.fetchall()
            conn.close()

            for (payload_str,) in rows:
                skill_data = json.loads(payload_str)
                triggers = skill_data.get("trigger_intents", [])
                if any(t.lower() in intent_lower for t in triggers):
                    return skill_data
        except Exception:
            pass

        # 2. Remote community Hub fallback
        catalog = self.fetch_community_skills()
        for skill_name, skill_data in catalog.items():
            triggers = skill_data.get("trigger_intents", [])
            if any(t.lower() in intent_lower for t in triggers):
                return skill_data
        return None

    def _resolve_read_target(self) -> str:
        user = self.bridge.get_authenticated_user()
        if user:
            return f"{user}/oss-agent-collective-data"
        return self.DEFAULT_COMMUNITY_REPO
