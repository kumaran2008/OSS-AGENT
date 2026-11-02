import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple, Union


@dataclass
class EndpointDefinition:
    backend_id: str
    provider: str                      # "anthropic", "deepseek", "openai", "openrouter"
    model_name: str
    context_window: int
    cost_per_m_in: float
    cost_per_m_out: float
    api_base_url: str
    api_key_env_var: Optional[str] = None


class UniversalModelSwitcher:
    """
    100% Cloud-First Dynamic Model Switcher with OpenRouter Auto-Discovery:
    - Auto-discovers and registers models via OpenRouter's live API catalog.
    - Zero local SLM requirements.
    - Manages room and task bindings across all rooms.
    - Synchronizes live RoomsEngine and model_registry.json.
    """

    DEFAULT_REGISTRY_PATH = Path("agent/pa_scaffolder/model_registry.json")
    OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"

    # Embedded seed catalog for resilient offline/fallback operation
    BUILTIN_OPENROUTER_CATALOG = [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128000,
            "pricing": {"prompt": "0.0000025", "completion": "0.00001"}
        },
        {
            "id": "anthropic/claude-3.7-sonnet",
            "name": "Anthropic: Claude 3.7 Sonnet",
            "context_length": 200000,
            "pricing": {"prompt": "0.000003", "completion": "0.000015"}
        },
        {
            "id": "deepseek/deepseek-r1",
            "name": "DeepSeek: DeepSeek R1",
            "context_length": 64000,
            "pricing": {"prompt": "0.00000055", "completion": "0.00000219"}
        },
        {
            "id": "qwen/qwen-2.5-coder-32b-instruct",
            "name": "Qwen: Qwen 2.5 Coder 32B Instruct",
            "context_length": 131072,
            "pricing": {"prompt": "0.0000002", "completion": "0.0000002"}
        },
        {
            "id": "google/gemini-2.5-flash",
            "name": "Google: Gemini 2.5 Flash",
            "context_length": 1000000,
            "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}
        },
        {
            "id": "openai/gpt-4.5-preview",
            "name": "OpenAI: GPT-4.5 Preview",
            "context_length": 128000,
            "pricing": {"prompt": "0.000075", "completion": "0.00015"}
        }
    ]

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or self.DEFAULT_REGISTRY_PATH
        self.endpoints: Dict[str, EndpointDefinition] = {}
        self.room_assignments: Dict[str, str] = {}
        self.task_assignments: Dict[str, str] = {}
        self._cached_catalog: Optional[List[Dict[str, Any]]] = None
        self.load_registry()

    def load_registry(self) -> bool:
        if not self.registry_path.exists():
            return False

        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            self.room_assignments = data.get("room_assignments", {})
            self.task_assignments = data.get("task_assignments", {})
            raw_endpoints = data.get("endpoints", {})
            self.endpoints = {}

            for b_id, cfg in raw_endpoints.items():
                # Filter out any legacy local providers
                if cfg.get("provider") in ["ollama", "local"]:
                    continue
                self.endpoints[b_id] = EndpointDefinition(
                    backend_id=b_id,
                    provider=cfg.get("provider", "openrouter"),
                    model_name=cfg.get("model_name", "deepseek-chat"),
                    context_window=cfg.get("context_window", 128000),
                    cost_per_m_in=cfg.get("cost_per_m_in", 0.14),
                    cost_per_m_out=cfg.get("cost_per_m_out", 0.28),
                    api_base_url=cfg.get("api_base_url", "https://openrouter.ai/api/v1"),
                    api_key_env_var=cfg.get("api_key_env_var", "OPENROUTER_API_KEY")
                )
            return True
        except Exception:
            return False

    def save_registry(self) -> bool:
        data = {
            "room_assignments": self.room_assignments,
            "task_assignments": self.task_assignments,
            "endpoints": {b_id: asdict(ep) for b_id, ep in self.endpoints.items()}
        }
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self.registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # OpenRouter Live Auto-Discovery Catalog
    # -------------------------------------------------------------------------
    def fetch_openrouter_catalog(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Queries OpenRouter /api/v1/models with fallback to builtin models."""
        if self._cached_catalog and not force_refresh:
            return self._cached_catalog

        try:
            req = urllib.request.Request(self.OPENROUTER_CATALOG_URL, headers={
                "User-Agent": "oss-agent/2.0 (OpenRouter Auto-Resolver)"
            })
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                if models:
                    self._cached_catalog = models
                    return models
        except Exception:
            pass

        self._cached_catalog = self.BUILTIN_OPENROUTER_CATALOG
        return self._cached_catalog

    def resolve_and_register_openrouter(self, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Searches OpenRouter's catalog for a model query (e.g. 'gpt-4.5', 'qwen coder', 'claude 3.7').
        Auto-registers the endpoint with true pricing and context length.
        Returns: (success, message, backend_id)
        """
        clean_q = query.lower().replace("_", " ").replace("-", " ").strip()
        catalog = self.fetch_openrouter_catalog()

        best_match = None
        for item in catalog:
            m_id = item.get("id", "").lower()
            m_name = item.get("name", "").lower()
            tokens = clean_q.split()

            if all(t in m_id or t in m_name for t in tokens):
                best_match = item
                break

        if not best_match:
            # Fuzzy fallback on any token
            for item in catalog:
                m_id = item.get("id", "").lower()
                m_name = item.get("name", "").lower()
                if any(t in m_id or t in m_name for t in clean_q.split() if len(t) > 2):
                    best_match = item
                    break

        if not best_match:
            return False, f"Could not find model matching '{query}' in OpenRouter catalog.", None

        # Extract attributes
        model_id = best_match.get("id")
        context_len = int(best_match.get("context_length", 128000))
        pricing = best_match.get("pricing", {})

        # Pricing per million tokens
        p_in = round(float(pricing.get("prompt", 0.0)) * 1_000_000.0, 4)
        p_out = round(float(pricing.get("completion", 0.0)) * 1_000_000.0, 4)

        backend_id = model_id.split("/")[-1].replace(":", "_").replace(".", "_")

        ep = EndpointDefinition(
            backend_id=backend_id,
            provider="openrouter",
            model_name=model_id,
            context_window=context_len,
            cost_per_m_in=p_in,
            cost_per_m_out=p_out,
            api_base_url="https://openrouter.ai/api/v1",
            api_key_env_var="OPENROUTER_API_KEY"
        )

        self.endpoints[backend_id] = ep
        self.save_registry()

        return True, f"Auto-discovered and registered '{backend_id}' ({best_match.get('name')}) via OpenRouter. Context: {context_len:,} tokens, Pricing: ${p_in}/${p_out} per 1M.", backend_id

    # -------------------------------------------------------------------------
    # Room & Task Switching API
    # -------------------------------------------------------------------------
    def switch_room_model(self, room_name: Union[str, Any], backend_id: str, rooms_engine: Optional[Any] = None) -> Tuple[bool, str]:
        self.load_registry()
        clean_room = (room_name.value if hasattr(room_name, 'value') else str(room_name)).lower().strip()
        clean_backend = backend_id.strip()

        # If backend not registered, attempt auto-resolution from OpenRouter
        if clean_backend not in self.endpoints:
            ok, msg, resolved_id = self.resolve_and_register_openrouter(clean_backend)
            if ok and resolved_id:
                clean_backend = resolved_id
            else:
                return False, f"Unknown model backend '{backend_id}'. Auto-resolution failed: {msg}"

        self.room_assignments[clean_room] = clean_backend
        self.save_registry()

        if rooms_engine:
            self.sync_with_rooms_engine(rooms_engine)
        else:
            try:
                mod = sys.modules.get("agent.pa_scaffolder.rooms_engine")
                if mod and hasattr(mod, "MODE_REGISTRY") and hasattr(mod, "AgentMode"):
                    for mode_enum in mod.AgentMode:
                        if mode_enum.value == clean_room and mode_enum in mod.MODE_REGISTRY:
                            mod.MODE_REGISTRY[mode_enum].preferred_backend = clean_backend
            except Exception:
                pass

        target_model = self.endpoints[clean_backend].model_name
        return True, f"Switched {clean_room.upper()} room to '{clean_backend}' ({target_model})."

    def switch_task_model(self, task_name: Union[str, Any], backend_id: str) -> Tuple[bool, str]:
        self.load_registry()
        clean_task = (task_name.value if hasattr(task_name, 'value') else str(task_name)).lower().strip()
        clean_backend = backend_id.strip()

        if clean_backend not in self.endpoints:
            ok, msg, resolved_id = self.resolve_and_register_openrouter(clean_backend)
            if ok and resolved_id:
                clean_backend = resolved_id
            else:
                return False, f"Unknown task backend '{backend_id}'. Auto-resolution failed: {msg}"

        self.task_assignments[clean_task] = clean_backend
        self.save_registry()

        target_model = self.endpoints[clean_backend].model_name
        return True, f"Switched task '{clean_task}' to '{clean_backend}' ({target_model})."

    def register_new_model(
        self,
        backend_id: str,
        provider: str,
        model_name: str,
        context_window: int = 128000,
        cost_per_m_in: float = 1.0,
        cost_per_m_out: float = 3.0,
        api_base_url: str = "https://api.openai.com/v1",
        api_key_env_var: Optional[str] = None
    ) -> Tuple[bool, str]:
        self.load_registry()
        ep = EndpointDefinition(
            backend_id=backend_id,
            provider=provider.lower().strip(),
            model_name=model_name.strip(),
            context_window=context_window,
            cost_per_m_in=cost_per_m_in,
            cost_per_m_out=cost_per_m_out,
            api_base_url=api_base_url.rstrip('/'),
            api_key_env_var=api_key_env_var
        )
        self.endpoints[backend_id] = ep
        self.save_registry()
        return True, f"Registered new cloud model '{backend_id}' ({model_name} via {provider})."

    def list_models(self) -> List[Dict[str, Any]]:
        self.load_registry()
        res = []
        for b_id, ep in self.endpoints.items():
            assigned_rooms = [r for r, b in self.room_assignments.items() if b == b_id]
            assigned_tasks = [t for t, b in self.task_assignments.items() if b == b_id]
            res.append({
                "backend_id": b_id,
                "model_name": ep.model_name,
                "provider": ep.provider,
                "context_window": ep.context_window,
                "pricing_in_out": f"${ep.cost_per_m_in}/${ep.cost_per_m_out} per 1M",
                "assigned_rooms": assigned_rooms,
                "assigned_tasks": assigned_tasks
            })
        return res

    def get_active_overview(self) -> Dict[str, Any]:
        self.load_registry()
        return {
            "rooms": {r: f"{b} ({self.endpoints.get(b, EndpointDefinition(b, '', b, 0, 0, 0, '')).model_name})" for r, b in self.room_assignments.items()},
            "tasks": {t: f"{b} ({self.endpoints.get(b, EndpointDefinition(b, '', b, 0, 0, 0, '')).model_name})" for t, b in self.task_assignments.items()}
        }

    def sync_with_rooms_engine(self, rooms_engine: Any):
        try:
            for mode_enum in rooms_engine.REGISTRY.keys():
                assigned_backend = self.room_assignments.get(mode_enum.value)
                if assigned_backend:
                    rooms_engine.REGISTRY[mode_enum].preferred_backend = assigned_backend
        except Exception:
            pass

    def get_endpoint_for_room(self, room_name: Union[str, Any]) -> EndpointDefinition:
        self.load_registry()
        clean_room = (room_name.value if hasattr(room_name, 'value') else str(room_name)).lower().strip()
        b_id = self.room_assignments.get(clean_room, "deepseek_flash")
        return self.endpoints.get(b_id, EndpointDefinition(b_id, "deepseek", "deepseek-chat", 64000, 0.14, 0.28, "https://api.deepseek.com/v1"))

    def get_endpoint_for_task(self, task_name: Union[str, Any]) -> EndpointDefinition:
        self.load_registry()
        clean_task = (task_name.value if hasattr(task_name, 'value') else str(task_name)).lower().strip()
        b_id = self.task_assignments.get(clean_task, "deepseek_flash")
        return self.endpoints.get(b_id, EndpointDefinition(b_id, "deepseek", "deepseek-chat", 64000, 0.14, 0.28, "https://api.deepseek.com/v1"))
