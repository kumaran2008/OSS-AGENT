import time
import requests
from typing import Dict, List, Tuple
from config.settings import settings


class ProviderCallError(Exception):
    pass


def _retry_post(url: str, headers: dict, payload: dict, timeout: int = 90, retries: int = 4) -> dict:
    backoff = 2.0
    last_error = None
    for attempt in range(retries):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if res.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            res.raise_for_status()
            return res.json()
        except Exception as e:
            last_error = e
            if attempt == retries - 1:
                raise ProviderCallError(f"Call failed after {retries} attempts: {e}") from e
            time.sleep(backoff)
            backoff *= 2
    raise ProviderCallError(f"Call failed: {last_error}")


class AnthropicDirectClient:
    """Calls Anthropic's native API directly — no OpenRouter markup."""

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set.")

        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_messages.append(m)

        headers = {
            "x-api-key": settings.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_msg.strip():
            payload["system"] = system_msg.strip()

        data = _retry_post("https://api.anthropic.com/v1/messages", headers, payload)
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = {
            "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
        }
        return text, usage


class OpenAIDirectClient:
    """Calls OpenAI's native API directly — no OpenRouter markup."""

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set.")

        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, "temperature": temperature}

        data = _retry_post("https://api.openai.com/v1/chat/completions", headers, payload)
        text = data["choices"][0]["message"]["content"]
        usage_raw = data.get("usage", {})
        usage = {
            "prompt_tokens": usage_raw.get("prompt_tokens", 0),
            "completion_tokens": usage_raw.get("completion_tokens", 0),
        }
        return text, usage


class GoogleDirectClient:
    """Calls Google's Gemini API directly — no OpenRouter markup."""

    def complete(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Tuple[str, Dict]:
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set.")

        contents = []
        system_instruction = None
        for m in messages:
            if m["role"] == "system":
                system_instruction = {"parts": [{"text": m["content"]}]}
            else:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {"contents": contents, "generationConfig": {"temperature": temperature}}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GOOGLE_API_KEY}"
        data = _retry_post(url, {"Content-Type": "application/json"}, payload)

        candidates = data.get("candidates", [])
        text = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)

        usage_raw = data.get("usageMetadata", {})
        usage = {
            "prompt_tokens": usage_raw.get("promptTokenCount", 0),
            "completion_tokens": usage_raw.get("candidatesTokenCount", 0),
        }
        return text, usage
