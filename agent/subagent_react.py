import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from tools.system_tier import CURRENT_TIER, HardwareTier
from llm.router import LLMRouter

class SubagentToolbox:
    """Lightweight tool execution: search and peer model delegation."""

    def __init__(self, router: LLMRouter):
        self.router = router

    def web_search(self, query: str) -> str:
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Android; Mobile; rv:109.0) Gecko/114.0 Firefox/114.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.DOTALL)
            clean_results = [re.sub(r"<[^>]+>", "", s).strip() for s in snippets[:3]]
            return "\n---\n".join(clean_results) if clean_results else "No relevant search results found."
        except Exception as e:
            return f"Search offline/failed: {str(e)}"

    def consult_peer(self, prompt: str) -> str:
        try:
            response, _ = self.router.complete_with_fallback(
                "analysis",
                [
                    {"role": "system", "content": "You are a secondary verification subagent. Answer concisely."},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.strip()
        except Exception as e:
            return f"Peer consultation failed: {str(e)}"


class AutonomousSubagent:
    """Autonomous subagent executing a bounded Reason-Act-Observe loop."""

    def __init__(self, role_name: str, system_prompt: str, router: LLMRouter):
        self.role_name = role_name
        self.system_prompt = system_prompt
        self.router = router
        self.tools = SubagentToolbox(router)
        self.max_steps = 2 if CURRENT_TIER == HardwareTier.TIER_LOW else 4

    def deliberate(self, objective: str) -> Dict[str, Any]:
        scratchpad = []

        for step in range(self.max_steps):
            full_prompt = (
                f"{self.system_prompt}\n\n"
                f"OBJECTIVE: {objective}\n\n"
                f"Scratchpad:\n" + ("\n".join(scratchpad) if scratchpad else "None") + "\n\n"
                "Respond in JSON format ONLY:\n"
                'If you need info: {"thought": "reasoning", "action": "web_search"|"consult_peer", "argument": "query"}\n'
                'If finished: {"thought": "reasoning", "action": "finish", "verdict": "final plan or output"}'
            )

            raw_resp, _ = self.router.complete_with_fallback(
                "planning",
                [{"role": "user", "content": full_prompt}]
            )

            try:
                clean = raw_resp.strip("` \n")
                if clean.startswith("json\n"):
                    clean = clean[5:]
                decision = json.loads(clean)
            except Exception:
                return {"role": self.role_name, "verdict": raw_resp.strip(), "steps": step + 1}

            action = decision.get("action")
            thought = decision.get("thought", "")

            if action == "finish" or step == self.max_steps - 1:
                return {
                    "role": self.role_name,
                    "verdict": decision.get("verdict", thought),
                    "steps": step + 1
                }

            arg = decision.get("argument", "")
            if action == "web_search":
                obs = self.tools.web_search(arg)
            elif action == "consult_peer":
                obs = self.tools.consult_peer(arg)
            else:
                obs = "Unknown action."

            scratchpad.append(f"Step {step+1} Thought: {thought}")
            scratchpad.append(f"Observation: {obs[:200]}")

        return {"role": self.role_name, "verdict": "Deliberation complete.", "steps": self.max_steps}
