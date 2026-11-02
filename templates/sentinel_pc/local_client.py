import json
import os
import urllib.request
from typing import Any, Dict, List, Optional


class LocalLLMClient:
    """Air-gapped HTTP client targeting local Ollama or llama.cpp OpenAI-compatible endpoints."""

    def __init__(self, endpoint_url: Optional[str] = None, model: Optional[str] = None):
        self.endpoint_url = endpoint_url or os.environ.get(
            "LOCAL_LLM_URL", "http://localhost:11434/v1/chat/completions"
        )
        self.model = model or os.environ.get("LOCAL_LLM_MODEL", "llama3.2")

    def query(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }
        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach local inference server at {self.endpoint_url}. "
                "Ensure Ollama (`ollama run llama3.2`) or llama-server is active."
            ) from e
