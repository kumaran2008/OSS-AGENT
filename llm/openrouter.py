import time
import requests
from typing import Dict, List, Tuple
from config.settings import settings


class OpenRouterClient:
    def __init__(self):
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        """Returns (response_text, usage_dict). usage_dict has prompt_tokens/completion_tokens (0 if unavailable)."""
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is missing from environment.")

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/oss-agent",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, "temperature": temperature}

        retries = 4
        backoff = 2.0
        last_error = None
        for attempt in range(retries):
            try:
                res = requests.post(self.url, headers=headers, json=payload, timeout=90)
                if res.status_code == 429:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                res.raise_for_status()
                data = res.json()
                usage = data.get("usage", {}) or {}
                if usage:
                    print(f"[LLM] model={model} tokens_in={usage.get('prompt_tokens')} "
                          f"tokens_out={usage.get('completion_tokens')}")
                return data["choices"][0]["message"]["content"], usage
            except Exception as e:
                last_error = e
                if attempt == retries - 1:
                    raise RuntimeError(f"OpenRouter call failed after {retries} attempts: {e}") from e
                time.sleep(backoff)
                backoff *= 2
        raise RuntimeError(f"OpenRouter call failed: {last_error}")
