from __future__ import annotations

import asyncio
import os
import sys
import time
import click
from pathlib import Path

from config.settings import validate_settings, settings
from tools.dashboard import dashboard, generate_dashboard
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine
from agent.pa_scaffolder.rooms_engine import AgentMode
from agent.pa_scaffolder.secure_vault import vault
from agent.pa_scaffolder.user_preferences import preferences
from agent.pa_scaffolder.setup_wizard import run_setup_wizard
from agent.pa_scaffolder.voice_daemon import launch_voice_daemon


async def run_interactive_pa_session(engine: UnifiedAsyncEngine) -> None:
    agent_name = engine.config.agent_name
    print("\n" + "=" * 64)
    print(f"🤖 {agent_name.upper()} PERSONAL AGENT WORKSTATION ACTIVE")
    print(f"• Active Mode:    [{engine.current_mode.value.upper()}]")
    print(f"• Active Backend: [{engine.config.active_backend}]")
    print(f"• Wake Words:     {', '.join(engine.config.wake_words)}")
    print("=" * 64)
    print("Type your instructions, commands, or 'exit'. (Use --voice for hands-free mode)\n")

    while True:
        try:
            mode_badge = engine.current_mode.value.upper()
            prompt_str = f"[{mode_badge}] {agent_name} > "
            user_input = input(prompt_str).strip()

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "/quit", "/exit"]:
                print(f"\nShutting down {agent_name}. Goodbye!")
                break

            if user_input.lower() in ["/setup", "setup", "/config"]:
                run_setup_wizard(force=True)
                continue

            if user_input.lower() in ["/models", "models"]:
                print("\n[🎯 Active Model Preferences]")
                for act, mdl in preferences.get_all().items():
                    print(f"  • {act.replace('_', ' ').capitalize()}: {mdl}")
                print()
                continue

            if user_input.lower() in ["--voice", "voice", "/voice"]:
                print("\n[⚡] Transitioning to Hands-Free Google Live Voice Session...")
                if not engine.google_live.is_configured():
                    print("[!] GEMINI_API_KEY is not configured in your environment.\n")
                else:
                    try:
                        await engine.google_live.start_live_session(modal_type="TEXT")
                    except KeyboardInterrupt:
                        print("\n[✓] Returned to REPL.")
                continue

            result = await engine.process_voice_turn(user_input)
            spoken = result.get("spoken_response") or result.get("content") or ""
            backend = result.get("execution_backend", "CORE")

            if spoken:
                print(f"\n[{backend}] ➔ {spoken}\n")
            else:
                print(f"\n[{backend}] ➔ Done.\n")

            if result.get("clipboard_copied"):
                print("[📋 Fix successfully applied to your clipboard]")

        except (KeyboardInterrupt, EOFError):
            print(f"\n\nSession terminated. Shutting down {agent_name}.")
            break
        except Exception as exc:
            print(f"\n[ERROR] Turn execution error: {str(exc)}\n")


@click.command()
@click.option("--voice", is_flag=True, default=False, help="Launch with dynamic voice listening daemon")
@click.option("--query", default=None, help="GitHub repo search query")
@click.option("--repo", default=None, help="Target a specific repo directly")
@click.option("--issue", default=None, type=int, help="Target a specific issue number directly")
@click.option("--dry-run", is_flag=True, default=False, help="Run without pushing changes")
def run(voice: bool, query: str | None, repo: str | None, issue: int | None, dry_run: bool) -> None:
    try:
        dashboard.start()
        dashboard.emit("STATE_CHANGE", {"state": "IDLE"})
    except Exception:
        pass

    # Ensure Vault Keys are loaded into environment
    if not vault.get_key("gemini") and not os.getenv("GEMINI_API_KEY"):
        run_setup_wizard()
    
    # Decrypt and populate active keys
    g_key = vault.get_key("gemini")
    if g_key:
        os.environ["GEMINI_API_KEY"] = g_key
    or_key = vault.get_key("openrouter")
    if or_key:
        os.environ["OPENROUTER_API_KEY"] = or_key

    engine = UnifiedAsyncEngine()

    if voice:
        print("[⚡] Launching Google Live Full-Duplex Multimodal Engine...")
        if not engine.google_live.is_configured():
            print("[!] GEMINI_API_KEY is not configured. Falling back to REPL.")
            asyncio.run(run_interactive_pa_session(engine))
        else:
            try:
                asyncio.run(engine.google_live.start_live_session(modal_type="TEXT"))
            except KeyboardInterrupt:
                print("\n[✓] Voice session closed cleanly.")
    else:
        # Default Interactive Terminal REPL
        asyncio.run(run_interactive_pa_session(engine))


if __name__ == "__main__":
    run()
