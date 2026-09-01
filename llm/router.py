import time
import requests
from typing import Callable, Dict, List, Optional, Tuple
from config.settings import settings
from llm.openrouter import OpenRouterClient
from models.schemas import ModelCallLog


class AllModelsFailedError(Exception):
    """Raised when every model — static chain and dynamic fallback — has failed."""
    pass


class ModelRouter:
    """
    Routes each task to a prioritized chain of models. On failure (API
    error, timeout, or output that fails validation), falls through to
    the next model in the chain.

    If ENABLE_DYNAMIC_MODEL_FALLBACK is set and the entire static chain
    for a task fails, queries OpenRouter's live /models catalog for
    additional candidates — filtered by a hard cost ceiling and minimum
    context length, never by name-substring guessing — and tries up to
    5 of those before giving up entirely.

    Every attempt (static or dynamic, success or failure) is recorded
    in self.call_log, with was_dynamic distinguishing the two so run
    history stays analyzable.
    """

    def __init__(self, task_chains: Dict[str, List[str]], client: Optional[OpenRouterClient] = None):
        self.task_chains = task_chains
        self.openrouter_client = client or OpenRouterClient()
        self.last_used_model: Dict[str, str] = {}
        self.call_log: List[ModelCallLog] = []
        self._dynamic_model_cache: Optional[Tuple[float, list]] = None  # (fetched_at, models)
        self._direct_clients = {}  # lazy-loaded: "anthropic-direct" / "openai-direct" / "google-direct"

    def _resolve_client_and_model(self, model: str):
        """
        Model strings prefixed with a direct-provider tag route to that
        provider's native API instead of OpenRouter — e.g.
        'anthropic-direct/claude-sonnet-5' calls Anthropic's own API with
        model='claude-sonnet-5', using ANTHROPIC_API_KEY, no OpenRouter
        markup. Anything without one of these prefixes goes through
        OpenRouter as before, unchanged.
        """
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
        chain = self.task_chains.get(task)
        if not chain:
            raise ValueError(f"No model chain configured for task '{task}'")

        errors = []
        attempted_models = set()

        # --- Static chain, exactly as before ---
        for model in chain:
            attempted_models.add(model)
            result = self._try_model(task, model, messages, validate_fn, temperature, errors, was_dynamic=False)
            if result is not None:
                return result

        # --- Dynamic fallback, opt-in only ---
        if settings.ENABLE_DYNAMIC_MODEL_FALLBACK:
            print(f"[Router] '{task}' — static chain exhausted, querying dynamic fallback...")
            try:
                candidates = self._get_dynamic_candidates(task, attempted_models)
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

    def _get_dynamic_candidates(self, task: str, attempted_models: set) -> List[str]:
        """
        Fetches (or reuses a cached) OpenRouter model catalog, filters by
        a hard cost ceiling and minimum context length, excludes anything
        already attempted this call, and returns up to 5 candidate IDs.
        Never filters by name-substring guessing.
        """
        models = self._fetch_model_catalog()

        estimated_tokens_needed = 4000  # conservative floor; real prompts vary by task
        max_price = settings.MAX_DYNAMIC_MODEL_PRICE_PER_MILLION

        candidates = []
        for m in models:
            model_id = m.get("id")
            if not model_id or model_id in attempted_models:
                continue

            pricing = m.get("pricing", {}) or {}
            try:
                prompt_price_per_token = float(pricing.get("prompt", "999"))
            except (TypeError, ValueError):
                continue
            price_per_million = prompt_price_per_token * 1_000_000
            if price_per_million > max_price:
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
            if now - fetched_at < settings.DYNAMIC_MODEL_CACHE_TTL_SECONDS:
                return cached_models

        headers = {}
        if settings.OPENROUTER_API_KEY:
            headers["Authorization"] = f"Bearer {settings.OPENROUTER_API_KEY}"

        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        models = response.json().get("data", [])

        self._dynamic_model_cache = (now, models)
        return models

