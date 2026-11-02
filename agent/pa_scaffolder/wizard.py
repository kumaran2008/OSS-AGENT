import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

from agent.pa_scaffolder.schemas import (
    PersonalAgentConfig,
    AgentPersona,
    OperatorProfile,
    InferenceConfig
)
from agent.pa_scaffolder.scaffolder import PersonalAgentScaffolder
from agent.core.branding import BRAND


class DeploymentWizard:
    """
    Interactive deployment engine that provisions an end-to-end
    Personal Agent package directly into the user's system.
    """
    def __init__(self, target_home: Optional[str] = None):
        self.target_home = Path(target_home or (Path.home() / ".personal_agent")).resolve()
        self.is_termux = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ

    def get_system_ram_gb(self) -> float:
        try:
            if sys.platform.startswith("linux") or self.is_termux:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            return round(int(line.split()[1]) / (1024 * 1024), 2)
            elif sys.platform == "darwin":
                out = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
                return round(int(out) / (1024**3), 2)
        except Exception:
            pass
        return 4.0

    def run_interactive(self) -> Path:
        print(BRAND.get_banner())
        print(">>> INITIALIZING PERSONAL AGENT DEPLOYMENT WIZARD <<<\n")

        ram = self.get_system_ram_gb()
        can_run_local = ram >= 6.0 and not self.is_termux

        # 1. Agent Identity
        print("--- [1/4] COMPANION IDENTITY ---")
        agent_name = input(f"Enter your Personal Agent's name (default: '{BRAND.pa_default_companion_name}'): ").strip()
        agent_name = agent_name or BRAND.pa_default_companion_name

        tone = input("Choose tone style (1: Supportive Hype, 2: Laser-focused Builder, 3: Cyberpunk Minimalist): ").strip()
        tone_map = {
            "1": "Supportive & High Energy",
            "2": "Laser-focused Builder",
            "3": "Cyberpunk Minimalist"
        }
        chosen_tone = tone_map.get(tone, "Supportive & High Energy")

        # 2. Operator Profile & Habits
        print("\n--- [2/4] OPERATOR SCHEDULE & PREFERENCES ---")
        call_sign = input("What should your agent call you? (default: 'Operator'): ").strip() or "Operator"
        wake_time = input("Daily wake-up time (default: '07:00'): ").strip() or "07:00"
        gym_time = input("Daily gym/exercise time (default: '18:30 - 19:30'): ").strip() or "18:30 - 19:30"
        daily_calories = input("Daily target calories (default: 2200): ").strip() or "2200"

        # 3. Model Engine Selection
        print("\n--- [3/4] INFERENCE ENGINE ROUTING ---")
        print(f"[*] Detected RAM: {ram} GB | Environment: {'Mobile/Termux' if self.is_termux else sys.platform}")
        print("  [1] OpenRouter (Multi-model provider API)")
        print("  [2] Direct Commercial API (DeepSeek / OpenAI / Anthropic / Groq)")
        print("  [3] Zero-Cost App Automation (Free browser/app bridge)")
        if can_run_local:
            print("  [4] Local Model Runner (Ollama auto-provisioned)")
        else:
            print("  [-] [Option 4 Disabled]: Insufficient RAM or environment for local LLMs.")

        engine_choice = input("\nSelect Engine (1-4): ").strip()
        inf_config = InferenceConfig()

        if engine_choice == "2":
            inf_config.engine = "direct_api"
            provider = input("Select Provider (deepseek / openai / anthropic / groq): ").strip().lower()
            key = input(f"Paste your {provider.upper()} API key: ").strip()
            inf_config.api_key = key
            if provider == "deepseek":
                inf_config.base_url = "https://api.deepseek.com/v1"
                inf_config.model = "deepseek-chat"
            elif provider == "groq":
                inf_config.base_url = "https://api.groq.com/openai/v1"
                inf_config.model = "llama-3.3-70b-versatile"
            elif provider == "anthropic":
                inf_config.base_url = "https://api.anthropic.com/v1"
                inf_config.model = "claude-3-5-sonnet"
            else:
                inf_config.base_url = "https://api.openai.com/v1"
                inf_config.model = "gpt-4o"

        elif engine_choice == "3":
            inf_config.engine = "app_automation"
            inf_config.app_mode = True
            inf_config.app_target = input("Target web application (chatgpt / claude): ").strip().lower() or "chatgpt"

        elif engine_choice == "4" and can_run_local:
            inf_config.engine = "local_ollama"
            inf_config.base_url = "http://127.0.0.1:11434/v1"
            inf_config.model = "qwen2.5-coder:7b"
            inf_config.api_key = "ollama"

        else:
            inf_config.engine = "openrouter"
            inf_config.base_url = "https://openrouter.ai/api/v1"
            key = input("Enter OpenRouter API Key: ").strip()
            inf_config.api_key = key
            inf_config.model = input("Preferred model (default: 'anthropic/claude-3.5-sonnet'): ").strip() or "anthropic/claude-3.5-sonnet"

        # 4. Assembly & Provisioning
        print("\n--- [4/4] DEPLOYING FILESYSTEM ARTIFACTS ---")
        config = PersonalAgentConfig(
            persona=AgentPersona(
                name=agent_name,
                wake_word=agent_name.lower(),
                tone_style=chosen_tone
            ),
            operator=OperatorProfile(
                call_sign=call_sign,
                wake_time=wake_time,
                gym_time=gym_time,
                daily_calories_target=int(daily_calories)
            ),
            inference=inf_config,
            pa_home=str(self.target_home)
        )

        scaffolder = PersonalAgentScaffolder(target_home=str(self.target_home))
        deployed_dir = scaffolder.deploy(config)

        # Write unified executable launcher script
        launcher_path = deployed_dir / "pa"
        launcher_script = f"""#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
python3 "${{SCRIPT_DIR}}/runtime/pa_runtime.py" "$@"
"""
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(launcher_script)
        os.chmod(launcher_path, 0o755)

        print(f"\n[✓] Deployment Complete! {agent_name} is active in: {deployed_dir}")
        print(f"[*] Executable created: {launcher_path}")
        return deployed_dir
