import json
import time
import requests
from typing import Dict, Generator, List, Optional, Tuple
from config.settings import settings


class OpenRouterClient:
    def __init__(self):
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.credits_url = "https://openrouter.ai/api/v1/credits"
        self.key_url = "https://openrouter.ai/api/v1/key"

    def get_headers(self) -> Dict[str, str]:
        key = getattr(settings, "OPENROUTER_API_KEY", "")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is missing from environment.")
        return {
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://github.com/oss-agent",
            "X-Title": "OSS-Agent",
            "Content-Type": "application/json",
        }

    def fetch_balance(self) -> float:
        """Fetches remaining usable credits in USD."""
        try:
            res = requests.get(self.credits_url, headers=self.get_headers(), timeout=8)
            if res.status_code == 200:
                data = res.json().get("data", {})
                total_credits = float(data.get("total_credits", 0.0))
                total_usage = float(data.get("total_usage", 0.0))
                return max(0.0, total_credits - total_usage)
        except Exception:
            pass

        try:
            res = requests.get(self.key_url, headers=self.get_headers(), timeout=8)
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

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        """Returns (response_text, usage_dict). usage_dict has prompt_tokens/completion_tokens."""
        payload = {"model": model, "messages": messages, "temperature": temperature}

        retries = 4
        backoff = 2.0
        last_error = None

        for attempt in range(retries):
            try:
                res = requests.post(self.url, headers=self.get_headers(), json=payload, timeout=90)
                if res.status_code == 429:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                res.raise_for_status()
                data = res.json()
                usage = data.get("usage", {}) or {}
                if usage:
                    print(
                        f"[LLM] model={model} tokens_in={usage.get('prompt_tokens', 0)} "
                        f"tokens_out={usage.get('completion_tokens', 0)}"
                    )
                return data["choices"][0]["message"]["content"], usage
            except Exception as e:
                last_error = e
                if attempt == retries - 1:
                    raise RuntimeError(f"OpenRouter call failed after {retries} attempts: {e}") from e
                time.sleep(backoff)
                backoff *= 2

        raise RuntimeError(f"OpenRouter call failed: {last_error}")

    def complete_stream(
        self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2
    ) -> Generator[str, None, None]:
        """Streams chunk tokens in real-time for live typewriter UI updates."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        res = requests.post(self.url, headers=self.get_headers(), json=payload, timeout=60, stream=True)
        res.raise_for_status()

        for line in res.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8").strip()
            if decoded.startswith("data: "):
                data_str = decoded[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        yield token
                except Exception:
                    continue
