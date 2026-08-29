from typing import Callable, Dict, List, Optional, Tuple
from llm.openrouter import OpenRouterClient
from models.schemas import ModelCallLog


class AllModelsFailedError(Exception):
    """Raised when every model in a task's fallback chain has failed."""
    pass


class ModelRouter:
    """
    Routes each task to a prioritized chain of models. On failure (API
    error, timeout, or output that fails validation), falls through to
    the next model in the chain instead of crashing the whole run.
    Every attempt (success or failure) is recorded in self.call_log for
    observability.
    """

    def __init__(self, task_chains: Dict[str, List[str]], client: Optional[OpenRouterClient] = None):
        self.task_chains = task_chains
        self.client = client or OpenRouterClient()
        self.last_used_model: Dict[str, str] = {}
        self.call_log: List[ModelCallLog] = []

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
        for model in chain:
            try:
                result, usage = self.client.complete(model, messages, temperature=temperature)
            except Exception as e:
                errors.append(f"{model}: {type(e).__name__}: {e}")
                self.call_log.append(ModelCallLog(
                    task=task, model_used=model, succeeded=False, error=str(e)
                ))
                print(f"[Router] '{task}' — {model} failed, trying next model...")
                continue

            if validate_fn and not validate_fn(result):
                errors.append(f"{model}: output failed validation")
                self.call_log.append(ModelCallLog(
                    task=task, model_used=model, succeeded=False, error="output_failed_validation",
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                ))
                print(f"[Router] '{task}' — {model} returned invalid output, trying next model...")
                continue

            self.last_used_model[task] = model
            self.call_log.append(ModelCallLog(
                task=task, model_used=model, succeeded=True,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            ))
            return result, model

        raise AllModelsFailedError(
            f"All models failed for task '{task}':\n" + "\n".join(errors)
        )
