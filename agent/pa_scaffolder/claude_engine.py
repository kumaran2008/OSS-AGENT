import os
import json
import base64
import urllib.request
import urllib.error
from pathlib import Path
from typing import Tuple, Optional, AsyncGenerator

from agent.pa_scaffolder.agent_config import AgentConfig


class ClaudeEngine:
    """
    Direct Anthropic / Frontier API Client (Zero external pip dependencies).
    Dynamically routes to user-specified models (Mythos 5.1, Fable, etc.)
    without hardcoded legacy defaults.
    """

    ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        # Priority: explicit param -> ENV var -> config file -> dynamic default
        cfg = AgentConfig()
        self.model = (
            model
            or os.getenv("ANTHROPIC_MODEL")
            or getattr(cfg, "claude_model", "mythos-5.1")
        )

    def is_configured(self) -> bool:
        return bool(self.api_key and (self.api_key.startswith("sk-ant-") or len(self.api_key) > 20))

    def analyze_screen_error(
        self,
        prompt: str,
        image_path: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Sends user context and screenshot to the selected frontier vision model.
        Enforces structured XML response containing code and reason.
        """
        if not self.is_configured():
            return False, "ANTHROPIC_API_KEY not configured."

        content_blocks = []

        # 1. Base64 encode screenshot if present
        if image_path and Path(image_path).exists():
            img_bytes = Path(image_path).read_bytes()
            b64_data = base64.b64encode(img_bytes).decode("utf-8")
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_data
                }
            })

        # 2. Add text prompt instructions
        structured_prompt = (
            f"{prompt}\n\n"
            "Diagnose the error and output strictly in this XML schema with NO extra pleasantries:\n"
            "<clipboard_code>\n"
            "[ONLY the raw, drop-in replacement code. Do not use markdown backticks]\n"
            "</clipboard_code>\n"
            "<spoken_reason>\n"
            "[1-2 punchy spoken sentences explaining why it failed and that the fix is ready]\n"
            "</spoken_reason>"
        )
        content_blocks.append({"type": "text", "text": structured_prompt})

        active_model = model_override or self.model

        payload = {
            "model": active_model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": content_blocks}]
        }

        req = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=20.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text_response = "".join(
                    block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
                )
                return True, text_response
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            return False, f"API HTTP Error {e.code}: {err_msg}"
        except Exception as e:
            return False, f"API Connection Failed: {str(e)}"

    async def stream_code_generation(
        self,
        prompt: str,
        model_override: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Streams code generation from the configured model."""
        if not self.is_configured():
            yield "API key is not configured. Please export ANTHROPIC_API_KEY."
            return

        active_model = model_override or self.model

        payload = {
            "model": active_model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True
        }

        req = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                for line in resp:
                    if not line:
                        continue
                    line_str = line.decode("utf-8").strip()
                    if line_str.startswith("data: "):
                        data_json = json.loads(line_str[6:])
                        if data_json.get("type") == "content_block_delta":
                            tok = data_json.get("delta", {}).get("text", "")
                            if tok:
                                yield tok
        except Exception as e:
            yield f" [Error streaming from {active_model}: {str(e)}]"
