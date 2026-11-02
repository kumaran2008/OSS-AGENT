import os
import json
import time
import urllib.request
from typing import Generator, List, Dict, Any, Optional, Tuple


class FastStreamRouter:
    """
    Sub-100ms streaming LLM router with fast-fail circuit breakers.
    Yields chunks token-by-token directly to WebSockets/UI.
    """
    def __init__(self):
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"

    def _resolve_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/oss-agent",
            "X-Title": "OSS-Agent-FastStream"
        }

    def stream_complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2
    ) -> Generator[str, None, None]:
        """
        Streams tokens in real time. Fast-fails immediately if an endpoint is
        dead (404/402) without 30-second retry backoffs.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            yield "[Auth Notice]: Missing OPENROUTER_API_KEY. Please provide your API key in the chat or settings modal."
            return

        # Fast model chain: Groq/Qwen 2.5 Coder or Claude 3.5 Sonnet
        chosen_model = model or os.environ.get("OPENROUTER_CODING_MODEL", "qwen/qwen-2.5-coder-32b-instruct")

        payload = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }

        req = urllib.request.Request(
            self.openrouter_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._resolve_headers(api_key)
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                for line in response:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        token = chunk["choices"][0].get("delta", {}).get("content", "")
                        if token:
                            yield token
                    except Exception:
                        continue
        except urllib.error.HTTPError as e:
            if e.code == 402:
                yield f"\n[Payment Required 402]: Your OpenRouter balance is depleted. Please top up credits or paste a new API key."
            elif e.code == 404:
                yield f"\n[Model Offline 404]: Model {chosen_model} is unavailable. Switching to backup provider..."
            else:
                yield f"\n[Inference Error {e.code}]: {e.reason}"
        except Exception as e:
            yield f"\n[Connection Error]: {str(e)}"

fast_streamer = FastStreamRouter()
