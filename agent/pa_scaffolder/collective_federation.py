import os
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class CommunityPatch:
    patch_id: str
    error_signature: str
    resolution_logic: str
    benchmark_regression_score: float
    verified: bool
    author_node: str
    timestamp: float


class CentralCollectiveSwarmFederation:
    """
    Global federated registry client for crowdsourced bug fixes and skill sharing.
    """
    def __init__(self, registry_root: Optional[Path] = None):
        self.registry_root = registry_root or (Path.home() / ".personal_agent" / "federation")
        self.registry_root.mkdir(parents=True, exist_ok=True)
        self.registry_db = self.registry_root / "community_patches.json"
        self._init_db()

    def _init_db(self):
        if not self.registry_db.exists():
            with open(self.registry_db, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def publish_verified_fix(
        self,
        error_signature: str,
        resolution_logic: str,
        benchmark_regression_score: float = 0.0,
        author_node: str = "node_aegis"
    ) -> CommunityPatch:
        """Publishes an oss-agent validated patch into the central collective knowledge base."""
        patch = CommunityPatch(
            patch_id=f"patch_{int(time.time()*1000)}",
            error_signature=error_signature,
            resolution_logic=resolution_logic,
            benchmark_regression_score=benchmark_regression_score,
            verified=(benchmark_regression_score <= 0.0),
            author_node=author_node,
            timestamp=time.time()
        )
        with open(self.registry_db, "r", encoding="utf-8") as f:
            data = json.load(f)
        data[error_signature] = patch.__dict__
        with open(self.registry_db, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return patch

    def query_and_apply_collective_fix(self, error_signature: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Checks if another user's oss-agent has already encountered and solved this error.
        If found, hot-applies the fix instantly.
        """
        with open(self.registry_db, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        patch_info = data.get(error_signature)
        if patch_info and patch_info.get("verified"):
            return True, patch_info
        return False, None
