import re
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from config.settings import settings
from llm.router import LLMRouter
from tools.agent_memory import UserProfileMemory, ConversationMemory, EpisodicExecutionMemory
from agent.security_agent import SecurityAgent
from agent.reviewer_agent import ReviewerAgent
from agent.core.branding import BRAND
from agent.pa_scaffolder.schemas import (
    PersonalAgentConfig,
    AgentPersona,
    OperatorProfile,
    InferenceConfig
)
from agent.pa_scaffolder.scaffolder import PersonalAgentScaffolder
from agent.pa_scaffolder.os_navigator import OSNavigator


class AutonomousChatBot:
    """
    Primary conversational and execution agent for oss-agent.
    Directly wired to memory, PA scaffolding, and OSNavigator automation.
    """

    def __init__(self):
        self.router = LLMRouter(settings.get_task_chains())
        self.user_mem = UserProfileMemory()
        self.conv_mem = ConversationMemory()
        self.ep_mem = EpisodicExecutionMemory()
        self.security = SecurityAgent(self.router)
        self.reviewer = ReviewerAgent(self.router)
        self.navigator = OSNavigator()

    def handle_device_action(self, user_input: str) -> Optional[str]:
        input_lower = user_input.lower().strip()

        # 1. App Launch Intent
        open_match = re.search(r'^(?:open|launch|start)\s+([a-zA-Z0-9_\-]+)', input_lower)
        if open_match:
            app = open_match.group(1)
            ok, msg = self.navigator.open_app(app)
            return f"[OS Action] {msg}"

        # 2. Scroll Intent
        if "scroll down" in input_lower:
            ok = self.navigator.scroll("down")
            return "[OS Action] Scrolled screen down." if ok else "[OS Action] Scroll command failed."
        elif "scroll up" in input_lower:
            ok = self.navigator.scroll("up")
            return "[OS Action] Scrolled screen up." if ok else "[OS Action] Scroll command failed."

        # 3. Element Click Intent
        click_match = re.search(r'^(?:click|tap)\s+([a-zA-Z0-9_\-]+)(?:\s+(?:on|in)\s+([a-zA-Z0-9_\-]+))?', input_lower)
        if click_match:
            target_elem = click_match.group(1)
            target_app = click_match.group(2) or "active"
            ok, msg = self.navigator.click_element(target_app, target_elem)
            return f"[OS Action] {msg}"

        # 4. Keypress Intent
        if input_lower in ("go home", "press home"):
            self.navigator.press_key("HOME")
            return "[OS Action] Sent HOME keyevent."
        if input_lower in ("press back", "go back"):
            self.navigator.press_key("BACK")
            return "[OS Action] Sent BACK keyevent."

        return None

    def handle_pa_builder_intent(self, user_input: str) -> Optional[str]:
        input_lower = user_input.lower()
        build_triggers = ["build pa", "create pa", "build personal agent", "create personal agent", "make companion", "setup pa"]
        
        if not any(trigger in input_lower for trigger in build_triggers):
            return None

        name_match = re.search(r'(?:named|name|call it|called)\s+([a-zA-Z0-9_\-]+)', user_input, re.IGNORECASE)
        if name_match:
            raw = name_match.group(1)
            agent_name = raw[0].upper() + raw[1:]
        else:
            agent_name = BRAND.pa_default_companion_name

        tone = "Supportive & High Energy"
        if "builder" in input_lower or "focus" in input_lower or "code" in input_lower:
            tone = "Laser-focused Builder"
        elif "minimal" in input_lower or "cyber" in input_lower or "quiet" in input_lower:
            tone = "Cyberpunk Minimalist"

        operator_call_sign = self.user_mem.profile.get("user_name", "Operator")
        target_path = Path.home() / ".personal_agent"
        config = PersonalAgentConfig(
            persona=AgentPersona(name=agent_name, wake_word=agent_name.lower(), tone_style=tone),
            operator=OperatorProfile(call_sign=operator_call_sign),
            inference=InferenceConfig(engine="openrouter" if settings.OPENROUTER_API_KEY else "app_automation"),
            pa_home=str(target_path)
        )

        scaffolder = PersonalAgentScaffolder(target_home=str(target_path))
        deployed_dir = scaffolder.deploy(config)

        launcher_path = deployed_dir / "pa"
        launcher_script = f'#!/usr/bin/env bash\npython3 "{deployed_dir}/runtime/pa_runtime.py" "$@"\n'
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(launcher_script)
        launcher_path.chmod(0o755)

        return (
            f"Personal Agent '{agent_name}' built and deployed to: `{deployed_dir}`\n\n"
            f"• **Tone**: {tone}\n"
            f"• **Operator**: {operator_call_sign}\n"
            f"• **Cognitive Brain**: `{deployed_dir}/memory/brain.db` (Initialized)\n"
            f"• **OS Automation**: Wired directly to OSNavigator\n"
            f"• **Launcher**: Run `~/.personal_agent/pa`"
        )

    # Backward compatibility alias
    _handle_pa_builder_intent = handle_pa_builder_intent

    def _build_system_prompt(self, user_query: str) -> str:
        base_prompt = (
            f"You are {BRAND.company_name} OSS-Agent, a production engineering AI wrapper.\n"
            f"You have direct access to system automation tools (opening apps, scrolling, tapping).\n"
            f"Always keep responses concise, technical, and immediately actionable."
        )
        user_context = self.user_mem.get_system_prompt_context()
        recalled_chats = self.conv_mem.search_past_topics(user_query, limit=2)
        history_context = ""
        if recalled_chats:
            history_context = "\n[Relevant Past Context]\n" + "\n".join(recalled_chats) + "\n"
        return f"{base_prompt}\n{user_context}\n{history_context}"

    def reply(self, user_input: str) -> str:
        self.conv_mem.log_message("user", user_input)

        device_resp = self.handle_device_action(user_input)
        if device_resp:
            self.conv_mem.log_message("assistant", device_resp)
            return device_resp

        builder_resp = self.handle_pa_builder_intent(user_input)
        if builder_resp:
            self.conv_mem.log_message("assistant", builder_resp)
            return builder_resp

        recent_turns = self.conv_mem.get_recent_history(limit=6)
        messages = [{"role": "system", "content": self._build_system_prompt(user_input)}]
        messages.extend(recent_turns)

        try:
            response_text, _ = self.router.complete_with_fallback("chat", messages)
        except Exception as e:
            response_text = f"Local agent fallback: I am standing by. (Engine note: {e})"

        self.conv_mem.log_message("assistant", response_text)
        return response_text
