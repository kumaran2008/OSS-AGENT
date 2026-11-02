import json
import urllib.request
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional, Tuple
from agent.pa_scaffolder.graph_brain import GraphBrainDB
from agent.pa_scaffolder.slm_manager import SLMScaffolder


class LocalSLMEngine:
    """
    Local Reasoning SLM Engine.
    Detects running llama-server (:8080) or Ollama (:11434).
    Falls back to zero-cost memory-grounded advisor if offline.
    """

    def __init__(self, memory: Optional[GraphBrainDB] = None, model_key: str = "qwen2.5_0.5b"):
        self.memory = memory or GraphBrainDB()
        self.scaffolder = SLMScaffolder()
        self.model_key = model_key

    def is_local_server_active(self) -> Tuple[bool, str]:
        """Detects if an OpenAI-compatible local runner is active."""
        # 1. Check llama-server (:8080)
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/health", method="GET")
            with urllib.request.urlopen(req, timeout=0.2) as resp:
                if resp.status == 200:
                    return True, "http://127.0.0.1:8080/v1/chat/completions"
        except Exception:
            pass

        # 2. Check Ollama (:11434)
        try:
            req = urllib.request.Request("http://127.0.0.1:11434", method="GET")
            with urllib.request.urlopen(req, timeout=0.2) as resp:
                if resp.status == 200:
                    return True, "http://127.0.0.1:11434/v1/chat/completions"
        except Exception:
            pass

        return False, ""

    async def stream_tokens(
        self,
        prompt: str,
        persona_name: str = "Hype"
    ) -> AsyncGenerator[str, None]:
        server_active, endpoint = self.is_local_server_active()

        # 1. Stream from active local daemon
        if server_active:
            payload = {
                "model": "local_slm",
                "messages": [
                    {"role": "system", "content": f"You are {persona_name}, a sharp AI companion. Give concise, step-by-step reasoning in 1-2 punchy sentences."},
                    {"role": "user", "content": prompt}
                ],
                "stream": True,
                "temperature": 0.4
            }
            queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            def _sync_worker():
                try:
                    req = urllib.request.Request(
                        endpoint,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=10.0) as resp:
                        for line in resp:
                            if not line:
                                continue
                            line_str = line.decode("utf-8").strip()
                            if line_str.startswith("data: "):
                                d_str = line_str[6:].strip()
                                if d_str == "[DONE]":
                                    break
                                d_json = json.loads(d_str)
                                tok = d_json["choices"][0]["delta"].get("content", "")
                                if tok:
                                    queue.put_nowait(tok)
                except Exception:
                    pass
                finally:
                    queue.put_nowait(None)

            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, _sync_worker)

            while True:
                token = await queue.get()
                if token is None:
                    break
                yield token
            return

        # 2. Contextual In-Memory Reasoning Advisor (Zero Network, Zero Token Cost)
        p_lower = prompt.lower().strip()

        recent_topic = "engineering"
        try:
            with self.memory._get_conn() as conn:
                row = conn.execute(
                    "SELECT properties FROM nodes WHERE node_type = 'episodic' ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    p = json.loads(row[0])
                    recent_topic = p.get("utterance", "coding")
        except Exception:
            pass

        if any(w in p_lower for w in ["tired", "exhausted", "sleepy", "done for today"]):
            response_text = f"You've been pushing hard on {recent_topic}. Step away from the screen for 15 minutes, grab some water—I'll keep watch on the workspace."
        elif any(w in p_lower for w in ["how are you", "how's it going", "what's up"]):
            response_text = "All systems running at peak speed. Standing by for whatever we're building next."
        elif any(w in p_lower for w in ["advice", "tip", "suggest"]):
            response_text = "Keep your modules decoupled and test your edge cases early. Less technical debt, more velocity."
        elif any(w in p_lower for w in ["good job", "thanks", "thank you", "nice"]):
            response_text = "That's what I'm here for! Let's keep this momentum going."
        else:
            response_text = f"Got you covered. Local engine is focused on '{prompt}'—ready to execute."

        for word in response_text.split(" "):
            yield word + " "
            await asyncio.sleep(0.015)
