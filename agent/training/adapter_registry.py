import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class AdapterRegistry:
    """
    Tracks and registers trained LoRA/QLoRA adapters.
    Maintains versioning, target base models, and gate benchmark scores.
    """

    def __init__(self, registry_dir: str = ".adapters"):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.registry_dir / "adapters_manifest.json"
        self._init_manifest()

    def _init_manifest(self) -> None:
        if not self.manifest_file.exists():
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump({"active_adapters": {}, "history": []}, f, indent=2)

    def register_adapter(
        self,
        role: str,
        adapter_path: str,
        base_model: str,
        benchmark_score: float,
        training_samples: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Registers a newly trained adapter as the active adapter for a role."""
        with open(self.manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        record = {
            "role": role,
            "adapter_path": str(adapter_path),
            "base_model": base_model,
            "benchmark_score": benchmark_score,
            "training_samples": training_samples,
            "registered_at": time.time(),
            "metadata": metadata or {},
        }

        data["active_adapters"][role] = record
        data["history"].append(record)

        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return record

    def get_active_adapter(self, role: str) -> Optional[Dict[str, Any]]:
        with open(self.manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("active_adapters", {}).get(role)

    def list_all(self) -> Dict[str, Any]:
        with open(self.manifest_file, "r", encoding="utf-8") as f:
            return json.load(f)


adapter_registry = AdapterRegistry()
