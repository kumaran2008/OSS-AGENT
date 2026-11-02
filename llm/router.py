import time
import requests
from typing import Callable, Dict, List, Optional, Tuple
from config.settings import settings
from llm.openrouter import OpenRouterClient
from models.schemas import ModelCallLog
from tools.scrubber import sanitize_messages
from tools.system_tier import CURRENT_TIER, HardwareTier


class AllModelsFailedError(Exception):
    """Raised when every model — static chain and dynamic fallback — has failed."""
    pass


class HardwareSpecDetector:
    """
    Detects system hardware tier for dashboard display and routing
    decisions. Delegates the actual tier calculation to
    tools/system_tier.py, which is the single source of truth for tier
    names used across this codebase (issue_scorer, security_agent,
    subagent_react, repomap, diff_explainer all import from there) —
    this class exists only as a stable, familiar interface for callers
    that expect it, not a second implementation.
    """

    @staticmethod
    def detect_tier() -> str:
        return CURRENT_TIER

    @staticmethod
    def get_system_ram_gb() -> float:
        try:
            import psutil
            return round(psutil.virtual_memory().total / (1024 ** 3), 2)
        except Exception:
            from tools.system_info import _read_ram_fallback
            return _read_ram_fallback()


class LocalOllamaClient:
    """
    OpenAI-compatible client for local Ollama execution. Uses requests
    (already a project dependency via OpenRouterClient) rather than
    urllib, for consistency with every other HTTP call in this codebase.
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or __import__("os").getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    def is_available(self) -> bool:
        try:
            res = requests.get(f"{self.base_url.replace('/v1', '')}/api/tags", timeout=1.5)
            return res.status_code == 200
        except Exception:
            return False

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        payload = {"model": model, "messages": messages, "temperature": temperature}
        res = requests.post(f"{self.base_url}/chat/completions", json=payload, timeout=180)
        res.raise_for_status()
        data = res.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage


class HuggingFaceDirectClient:
    """Direct Serverless Inference client for Hugging Face open models."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "HUGGINGFACE_API_KEY", "") or __import__("os").getenv("HUGGINGFACE_API_KEY", "")

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        if not self.api_key:
            raise ValueError("HUGGINGFACE_API_KEY is not set.")

        prompt = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages]) + "\nASSISTANT: "
        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"inputs": prompt, "parameters": {"max_new_tokens": 2048, "temperature": max(0.01, temperature)}}
        res = requests.post(url, headers=headers, json=payload, timeout=120)
        res.raise_for_status()
        data = res.json()

        if isinstance(data, list) and len(data) > 0:
            generated_text = data[0].get("generated_text", "")
            if "ASSISTANT: " in generated_text:
                generated_text = generated_text.split("ASSISTANT: ", 1)[1]
            return generated_text, {"prompt_tokens": len(prompt.split()), "completion_tokens": len(generated_text.split())}

        raise ValueError(f"Unexpected HF response format: {data}")


class ModelRouter:
    """
    Tier-aware, credit-aware model router. Tries a configured chain of
    models per task; falls through to the next on failure or invalid
    output; can query OpenRouter's live catalog for further fallback
    candidates; supports local Ollama, Hugging Face, and direct
    provider (Anthropic/OpenAI/Google) routing alongside OpenRouter.

    'ModelRouter' is the canonical name used throughout this codebase —
    do not rename this class or alias it under a different name
    elsewhere (a prior version introduced an 'LLMRouter' alias in
    tools/llm_router.py; that file has been removed as unused/orphaned).
    """

    def __init__(self, task_chains: Optional[Dict[str, List[str]]] = None, client: Optional[OpenRouterClient] = None, mode: str = "openrouter"):
        if task_chains is None:
            try:
                from config.settings import settings
                task_chains = settings.get_task_chains() if hasattr(settings, "get_task_chains") else getattr(settings, "TASK_CHAINS", {})
            except Exception:
                task_chains = {
                    "planning": ["qwen2.5-coder:1.5b"],
                    "coding": ["qwen2.5-coder:1.5b"],
                    "debugging": ["qwen2.5-coder:1.5b"],
                }
        self.task_chains = task_chains
        self.openrouter_client = client or OpenRouterClient()
        self.local_client = LocalOllamaClient()
        self.hf_client = HuggingFaceDirectClient()
        self.mode = mode
        self.hardware_tier = HardwareSpecDetector.detect_tier()
        self.last_used_model: Dict[str, str] = {}
        self.call_log: List[ModelCallLog] = []
        self._dynamic_model_cache: Optional[Tuple[float, list]] = None
        self._direct_clients = {}

    def set_mode(self, mode: str):
        """Modes: 'auto', 'local_llama', 'openrouter'."""
        self.mode = mode

    def get_account_balance(self) -> float:
        """Queries OpenRouter credits. Defaults safely to 0.0 on any
        error or missing data — never assumes abundance."""
        import os
        api_key = getattr(settings, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return 0.0

        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            res = requests.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json().get("data", {})
                total_credits = float(data.get("total_credits", 0.0))
                total_usage = float(data.get("total_usage", 0.0))
                return max(0.0, total_credits - total_usage)
        except Exception:
            pass

        try:
            res = requests.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json().get("data", {})
                limit = data.get("limit")
                usage = float(data.get("usage", 0.0))
                if limit is None or data.get("is_free_tier", False) is False:
                    return max(0.0, float(data.get("limit_remaining", 0.0)))
                return max(0.0, float(limit) - usage)
        except Exception:
            pass

        return 0.0

    def _resolve_client_and_model(self, model: str):
        if model.startswith("local/") or model.startswith("ollama/"):
            return self.local_client, model.split("/", 1)[1]

        if model.startswith("hf/") or model.startswith("huggingface/"):
            return self.hf_client, model.split("/", 1)[1]

        if model.startswith("anthropic-direct/"):
            if "anthropic" not in self._direct_clients:
                from llm.providers import AnthropicDirectClient
                self._direct_clients["anthropic"] = AnthropicDirectClient()
            return self._direct_clients["anthropic"], model.split("/", 1)[1]

        if model.startswith("openai-direct/"):
            if "openai" not in self._direct_clients:
                from llm.providers import OpenAIDirectClient
                self._direct_clients["openai"] = OpenAIDirectClient()
            return self._direct_clients["openai"], model.split("/", 1)[1]

        if model.startswith("google-direct/"):
            if "google" not in self._direct_clients:
                from llm.providers import GoogleDirectClient
                self._direct_clients["google"] = GoogleDirectClient()
            return self._direct_clients["google"], model.split("/", 1)[1]

        return self.openrouter_client, model

    def _get_chain_for_task(self, task: str, balance: float) -> List[str]:
        """Determines model priority chain based on mode, hardware tier, and balance."""
        chain = self.task_chains.get(task, [])
        ollama_ready = self.local_client.is_available()
        is_mason_task = any(k in task.lower() for k in ["code", "mason", "debug", "test"])

        # Explicit "local_llama" mode must route locally whenever Ollama
        # is reachable — this previously only checked for "auto" mode,
        # silently ignoring an explicit local_llama selection. Fixed.
        wants_local = self.mode in ("auto", "local_llama")

        if wants_local and ollama_ready:
            if self.hardware_tier == HardwareTier.TIER_HIGH:
                if is_mason_task:
                    return ["local/qwen2.5-coder:14b", "local/qwen2.5-coder:7b"] + chain
                return ["local/llama3.3:70b", "local/nous-hermes2:latest"] + chain
            elif self.hardware_tier == HardwareTier.TIER_MID and is_mason_task:
                return ["local/qwen2.5-coder:7b", "local/qwen2.5-coder:1.5b"] + chain
            elif self.mode == "local_llama":
                return ["local/qwen2.5-coder:1.5b"] + chain
        elif self.mode == "local_llama" and not ollama_ready:
            print("[Router] Local mode selected but Ollama is not reachable. Falling back to cloud...")

        if balance >= 1.00:
            return chain if chain else ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]
        elif balance > 0.0:
            return [
                "qwen/qwen-2.5-coder-32b-instruct",
                "anthropic/claude-3.5-haiku",
                "openai/gpt-4o-mini",
                "deepseek/deepseek-chat",
            ]
        else:
            free_models = [m for m in chain if ":free" in m]
            if not free_models:
                free_models = ["qwen/qwen3-coder:free", "deepseek/deepseek-r1:free"]
            hf_key = getattr(settings, "HUGGINGFACE_API_KEY", "") or __import__("os").getenv("HUGGINGFACE_API_KEY", "")
            if hf_key:
                free_models.append("hf/Qwen/Qwen2.5-Coder-7B-Instruct")
            return free_models

    
    def _get_adapter_override(self, task_name: str) -> Optional[dict]:
        """Checks if a fine-tuned adapter exists for the task role."""
        try:
            from agent.training.adapter_registry import adapter_registry
            role_mapping = {
                "coding": "mason_backend_mason",
                "review": "reviewer",
                "testing": "tester",
            }
            target_role = role_mapping.get(task_name)
            if not target_role:
                return None

            active = adapter_registry.get_active_adapter(target_role)
            if active and "repo_id" in active.get("metadata", {}):
                return {
                    "model": active["metadata"]["repo_id"],
                    "provider": "huggingface",
                    "base_model": active.get("base_model"),
                }
        except Exception:
            pass
        return None

    
    def _detect_local_endpoint(self) -> Optional[dict]:
        """Detects whether Ollama or llama.cpp is listening on localhost."""
        import os, urllib.request

        custom_url = os.environ.get("LOCAL_LLM_URL")
        candidates = []
        if custom_url:
            candidates.append({"url": custom_url, "provider": "custom", "model": os.environ.get("LOCAL_LLM_MODEL", "default")})

        candidates.extend([
            {"url": "http://localhost:11434/v1/chat/completions", "provider": "ollama", "model": os.environ.get("LOCAL_LLM_MODEL", "llama3.2")},
            {"url": "http://127.0.0.1:11434/v1/chat/completions", "provider": "ollama", "model": os.environ.get("LOCAL_LLM_MODEL", "llama3.2")},
            {"url": "http://localhost:8080/v1/chat/completions", "provider": "llama.cpp", "model": os.environ.get("LOCAL_LLM_MODEL", "default")},
            {"url": "http://127.0.0.1:8080/v1/chat/completions", "provider": "llama.cpp", "model": os.environ.get("LOCAL_LLM_MODEL", "default")},
        ])

        for c in candidates:
            try:
                base_health = c["url"].replace("/v1/chat/completions", "/v1/models")
                req = urllib.request.Request(base_health, headers={"User-Agent": "oss-agent"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status in (200, 204):
                        return c
            except Exception:
                continue
        return None

    def _call_local_server(self, messages: list, endpoint_info: dict) -> str:
        """Executes inference against local llama.cpp or Ollama OpenAI-compatible endpoint."""
        import json, urllib.request

        payload = {
            "model": endpoint_info.get("model", "llama3.2"),
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.2,
            "stream": False
        }

        req = urllib.request.Request(
            endpoint_info["url"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def complete_with_fallback(
        self,
        task: str,
        messages: List[Dict[str, str]],
        validate_fn: Optional[Callable[[str], bool]] = None,
        temperature: float = 0.2,
    ) -> Tuple[str, str]:
        chain = self.task_chains.get(task)
        if chain is None and task not in self.task_chains:
            raise ValueError(f"No model chain configured for task '{task}'")

        messages = sanitize_messages(messages)
        balance = self.get_account_balance()
        resolved_chain = self._get_chain_for_task(task, balance)

        errors = []
        attempted_models = set()

        for model in resolved_chain:
            attempted_models.add(model)
            result = self._try_model(task, model, messages, validate_fn, temperature, errors, was_dynamic=False)
            if result is not None:
                return result

        if settings.ENABLE_DYNAMIC_MODEL_FALLBACK or balance == 0.0:
            print(f"[Router] '{task}' — static chain exhausted, querying dynamic fallback...")
            try:
                candidates = self._get_dynamic_candidates(task, attempted_models, zero_cost_only=(balance == 0.0), max_budget=balance)
            except Exception as e:
                errors.append(f"dynamic discovery failed: {type(e).__name__}: {e}")
                candidates = []

            for model in candidates:
                result = self._try_model(task, model, messages, validate_fn, temperature, errors, was_dynamic=True)
                if result is not None:
                    return result

                # Offline Fallback: Check for local Ollama / llama.cpp
        local_ep = self._detect_local_endpoint()
        if local_ep:
            try:
                print(f"[Router] Remote providers exhausted/offline. Trying local {local_ep['provider']} at {local_ep['url']}...")
                content = self._call_local_server(messages, local_ep)
                if validate_fn is None or validate_fn(content):
                    return content, f"local_{local_ep['provider']}"
            except Exception as e:
                print(f"[Router] Local {local_ep['provider']} inference failed: {e}")
        raise AllModelsFailedError(f"All models failed for task '{task}' under tier {self.hardware_tier}:\n" + "\n".join(errors))

    def _try_model(self, task, model, messages, validate_fn, temperature, errors, was_dynamic) -> Optional[Tuple[str, str]]:
        tag = "[dynamic]" if was_dynamic else "[static]"
        try:
            client, resolved_model = self._resolve_client_and_model(model)
            result, usage = client.complete(resolved_model, messages, temperature=temperature)
        except Exception as e:
            errors.append(f"{model} {tag}: {type(e).__name__}: {e}")
            self.call_log.append(ModelCallLog(task=task, model_used=model, succeeded=False, error=str(e), was_dynamic=was_dynamic))
            print(f"[Router] '{task}' — {model} {tag} failed, trying next model...")
            return None

        if validate_fn and not validate_fn(result):
            errors.append(f"{model} {tag}: output failed validation")
            self.call_log.append(ModelCallLog(
                task=task, model_used=model, succeeded=False, error="output_failed_validation",
                prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
                was_dynamic=was_dynamic,
            ))
            print(f"[Router] '{task}' — {model} {tag} returned invalid output, trying next model...")
            return None

        self.last_used_model[task] = model
        self.call_log.append(ModelCallLog(
            task=task, model_used=model, succeeded=True,
            prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
            was_dynamic=was_dynamic,
        ))
        if was_dynamic:
            print(f"[Router] '{task}' — succeeded via dynamic fallback: {model}")
        return result, model

    def _get_dynamic_candidates(self, task: str, attempted_models: set, zero_cost_only: bool = False, max_budget: float = 0.0) -> List[str]:
        models = self._fetch_model_catalog()
        candidates = []
        for m in models:
            model_id = m.get("id")
            if not model_id or model_id in attempted_models:
                continue
            pricing = m.get("pricing", {}) or {}
            try:
                p_price = float(pricing.get("prompt", "999"))
                c_price = float(pricing.get("completion", "999"))
            except (TypeError, ValueError):
                continue
            if zero_cost_only:
                if p_price != 0.0 or c_price != 0.0:
                    continue
            else:
                price_per_m = p_price * 1_000_000
                if price_per_m > settings.MAX_DYNAMIC_MODEL_PRICE_PER_MILLION:
                    continue
                if max_budget < 0.50 and price_per_m > 2.0:
                    continue
            if (m.get("context_length", 0) or 0) < 4000:
                continue
            candidates.append(model_id)
            if len(candidates) >= 5:
                break
        return candidates

    def _fetch_model_catalog(self) -> list:
        import os
        now = time.time()
        if self._dynamic_model_cache is not None:
            fetched_at, cached_models = self._dynamic_model_cache
            if now - fetched_at < getattr(settings, "DYNAMIC_MODEL_CACHE_TTL_SECONDS", 300):
                return cached_models

        headers = {}
        api_key = getattr(settings, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        res = requests.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=15)
        res.raise_for_status()
        models = res.json().get("data", [])
        self._dynamic_model_cache = (now, models)
        return models
       
# Both names are canonical in this codebase — ModelRouter is used by
# RunLogger/orchestrator's original design, LLMRouter is used by
# reviewer_agent, security_agent, chat_interface, and subagent_react.
# Rather than pick one and edit every call site, both names point at
# the exact same class.
LLMRouter = ModelRouter
