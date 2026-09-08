import os
import time
import requests
from typing import Callable, Dict, List, Optional, Tuple, Any
from config.settings import settings
from llm.openrouter import OpenRouterClient
from models.schemas import ModelCallLog
from tools.scrubber import sanitize_messages


class AllModelsFailedError(Exception):
    """Raised when every model — static chain and dynamic fallback — has failed."""
    pass


class LocalOllamaClient:
    """OpenAI-compatible client for local Ollama / Llama execution."""
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict[str, Any]]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        res = requests.post(f"{self.base_url}/chat/completions", json=payload, timeout=180)
        res.raise_for_status()
        data = res.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage


class ModelRouter:
    """
    Routes tasks intelligently based on hardware capabilities and account
    token balance. Supports local Ollama as well as balance-maintained
    OpenRouter tiers.
    """

    def __init__(
        self,
        task_chains: Dict[str, List[str]],
        client: Optional[OpenRouterClient] = None,
        mode: str = "openrouter"
    ):
        self.task_chains = task_chains
        self.openrouter_client = client or OpenRouterClient()
        self.local_client = LocalOllamaClient()
        self.mode = mode
        self.last_used_model: Dict[str, str] = {}
        self.call_log: List[ModelCallLog] = []
        self._dynamic_model_cache: Optional[Tuple[float, list]] = None
        self._direct_clients = {}

    def set_mode(self, mode: str):
        """Sets routing mode: 'local_llama' or 'openrouter'."""
        self.mode = mode

    def get_account_balance(self) -> float:
        """
        Queries OpenRouter's key/credits endpoints to check exact
        available credits. Returns balance in USD. On any failure or
        missing data, returns 0.0 — the safe assumption is "no budget",
        not "assume plenty", since overestimating balance risks routing
        to a model the account can't actually afford.
        """
        api_key = getattr(settings, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return 0.0

        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            res = requests.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json().get("data", {})
                limit = data.get("limit")
                usage = data.get("usage", 0)
                if limit is None or data.get("is_free_tier", False) is False:
                    return max(0.0, float(data.get("limit_remaining", 0.0)))
                return max(0.0, float(limit) - float(usage))
        except Exception:
            pass

        try:
            res = requests.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json().get("data", {})
                total_credits = data.get("total_credits", 0)
                total_usage = data.get("total_usage", 0)
                return max(0.0, float(total_credits) - float(total_usage))
        except Exception:
            pass

        return 0.0

    def _resolve_client_and_model(self, model: str):
        if self.mode == "local_llama":
            local_model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5-coder:7b")
            return self.local_client, local_model

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

    def complete_with_fallback(
        self,
        task: str,
        messages: List[Dict[str, str]],
        validate_fn: Optional[Callable[[str], bool]] = None,
        temperature: float = 0.2,
    ) -> Tuple[str, str]:
        # Redact any secret-looking strings before they leave this process.
        messages = sanitize_messages(messages)

        # 1. Local Llama path, if selected
        if self.mode == "local_llama":
            errors = []
            result = self._try_model(task, "local_llama", messages, validate_fn, temperature, errors, was_dynamic=False)
            if result is not None:
                return result
            print("[Router] Local model execution failed. Falling back to Cloud OpenRouter...")

        # 2. Cloud path with balance-aware tiering
        balance = self.get_account_balance()
        chain = self.task_chains.get(task, [])

        if balance > 0.0:
            print(f"[Balance Manager] Active OpenRouter credits found (${balance:.2f}).")
            if balance < 1.00:
                print("[Balance Manager] Low balance (<$1.00). Allocating budget-efficient paid models...")
                chain = [
                    "anthropic/claude-3.5-haiku",
                    "openai/gpt-4o-mini",
                    "qwen/qwen-2.5-coder-32b-instruct",
                    "deepseek/deepseek-chat",
                ]
            else:
                print("[Balance Manager] Healthy balance. Using configured static model chain.")
                if not chain:
                    chain = ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]
        else:
            print("[Balance Manager] Credit balance $0.00. Enforcing strict zero-cost (:free) models...")
            chain = [m for m in chain if ":free" in m]
            if not chain:
                # Reuse models already verified working elsewhere in this
                # project, rather than guessing unverified new free-model
                # names that risk 404ing.
                chain = ["qwen/qwen3-coder:free", "deepseek/deepseek-r1:free"]

        errors = []
        attempted_models = set()

        for model in chain:
            attempted_models.add(model)
            result = self._try_model(task, model, messages, validate_fn, temperature, errors, was_dynamic=False)
            if result is not None:
                return result

        if settings.ENABLE_DYNAMIC_MODEL_FALLBACK or balance == 0.0:
            print(f"[Router] '{task}' — static chain exhausted, querying dynamic fallback...")
            try:
                candidates = self._get_dynamic_candidates(
                    task, attempted_models, zero_cost_only=(balance == 0.0), max_budget=balance
                )
            except Exception as e:
                errors.append(f"dynamic discovery failed: {type(e).__name__}: {e}")
                candidates = []

            for model in candidates:
                result = self._try_model(task, model, messages, validate_fn, temperature, errors, was_dynamic=True)
                if result is not None:
                    return result

        raise AllModelsFailedError(
            f"All models failed for task '{task}':\n" + "\n".join(errors)
        )

    def _try_model(
        self,
        task: str,
        model: str,
        messages: List[Dict[str, str]],
        validate_fn: Optional[Callable[[str], bool]],
        temperature: float,
        errors: list,
        was_dynamic: bool,
    ) -> Optional[Tuple[str, str]]:
        tag = "[dynamic]" if was_dynamic else "[static]"
        try:
            client, resolved_model = self._resolve_client_and_model(model)
            result, usage = client.complete(resolved_model, messages, temperature=temperature)
        except Exception as e:
            errors.append(f"{model} {tag}: {type(e).__name__}: {e}")
            self.call_log.append(ModelCallLog(
                task=task, model_used=model, succeeded=False, error=str(e), was_dynamic=was_dynamic
            ))
            print(f"[Router] '{task}' — {model} {tag} failed, trying next model...")
            return None

        if validate_fn and not validate_fn(result):
            errors.append(f"{model} {tag}: output failed validation")
            self.call_log.append(ModelCallLog(
                task=task, model_used=model, succeeded=False, error="output_failed_validation",
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                was_dynamic=was_dynamic,
            ))
            print(f"[Router] '{task}' — {model} {tag} returned invalid output, trying next model...")
            return None

        self.last_used_model[task] = model
        self.call_log.append(ModelCallLog(
            task=task, model_used=model, succeeded=True,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            was_dynamic=was_dynamic,
        ))
        if was_dynamic:
            print(f"[Router] '{task}' — succeeded via dynamic fallback: {model}")
        return result, model

    def _get_dynamic_candidates(
        self, task: str, attempted_models: set, zero_cost_only: bool = False, max_budget: float = 0.0
    ) -> List[str]:
        models = self._fetch_model_catalog()
        estimated_tokens_needed = 4000
        max_price = settings.MAX_DYNAMIC_MODEL_PRICE_PER_MILLION

        candidates = []
        for m in models:
            model_id = m.get("id")
            if not model_id or model_id in attempted_models:
                continue

            pricing = m.get("pricing", {}) or {}
            try:
                prompt_price = float(pricing.get("prompt", "999"))
                completion_price = float(pricing.get("completion", "999"))
            except (TypeError, ValueError):
                continue

            if zero_cost_only:
                if prompt_price != 0.0 or completion_price != 0.0:
                    continue
            else:
                price_per_million = prompt_price * 1_000_000
                if price_per_million > max_price:
                    continue
                if max_budget < 0.50 and price_per_million > 2.0:
                    continue

            context_length = m.get("context_length", 0) or 0
            if context_length < estimated_tokens_needed:
                continue

            candidates.append(model_id)
            if len(candidates) >= 5:
                break

        return candidates

    def _fetch_model_catalog(self) -> list:
        now = time.time()
        if self._dynamic_model_cache is not None:
            fetched_at, cached_models = self._dynamic_model_cache
            if now - fetched_at < getattr(settings, "DYNAMIC_MODEL_CACHE_TTL_SECONDS", 300):
                return cached_models

        headers = {}
        api_key = getattr(settings, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        models = response.json().get("data", [])

        self._dynamic_model_cache = (now, models)
        return models
