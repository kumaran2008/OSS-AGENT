from __future__ import annotations
import sys
import time
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from oss_agent.system_probe import SystemAdapter
from oss_agent.config import load_settings, save_settings
from oss_agent.brain_memory import BrainMemory
from oss_agent.jev_engine import JevDecisionEngine

console = Console()

def run_onboarding():
    console.clear()
    console.print(Panel.fit("[bold cyan]OSS-AGENT: SYSTEM INITIALIZATION & ONBOARDING[/bold cyan]\n[dim]Ground-Up Production Scaffolding[/dim]", border_style="cyan"))

    # Step 1: System Hardware & Environment Sensing
    console.print("\n[bold yellow]Step 1: Inspecting Host Hardware & System Environment...[/bold yellow]")
    topo = SystemAdapter.inspect()
    console.print(f"  • Operating System: [green]{topo.os_name} {topo.os_release} ({topo.architecture})[/green]")
    console.print(f"  • CPU Topology:     [green]{topo.cpu_cores_physical} Physical Cores / {topo.cpu_cores_logical} Logical Threads[/green]")
    console.print(f"  • RAM Available:    [green]{topo.ram_available_gb} GB / {topo.ram_total_gb} GB Total[/green]")
    console.print(f"  • Microphone Input: [{'green' if topo.has_microphone else 'red'}]{'Available' if topo.has_microphone else 'Not Detected'}[/]")
    console.print(f"  • Display Server:   [{'green' if topo.has_display else 'red'}]{'Connected' if topo.has_display else 'Headless Server'}[/]")
    console.print(f"  • Detected Browsers: [cyan]{', '.join(topo.installed_browsers) or 'None'}[/cyan]")
    console.print(f"  • Installed CLIs:   [cyan]{', '.join(topo.installed_tools) or 'None'}[/cyan]")

    # Step 2: Name & Wake-word Selection
    console.print("\n[bold yellow]Step 2: Persona Identity & Wake Word[/bold yellow]")
    name = Prompt.ask("Choose a name for your Personal Agent", default="Jarvis")
    wake_word = Prompt.ask("Set the primary wake word", default=name.lower())
    continuous = Confirm.ask("Enable continuous listening (activates on voice detection even without wake word)?", default=True)

    # Step 3: Model Routing & TypeSafe Jev Engine
    console.print("\n[bold yellow]Step 3: Intelligence Routing & Jev Engine[/bold yellow]")
    jev_key = Prompt.ask("Enter TypeSafe Jev API Key (leave empty for local fallback engine)", default="", password=True)
    openrouter_key = Prompt.ask("Enter OpenRouter API Key (for LLM dispatch)", default="", password=True)

    # Step 4: Save Configuration & Initialize Brain Memory
    settings = load_settings()
    settings.agent_name = name
    settings.wake_word = wake_word
    settings.voice_continuous_listen = continuous
    settings.jev_api_key = jev_key or None
    settings.openrouter_api_key = openrouter_key or None
    settings.first_run_timestamp = time.time()
    save_settings(settings)

    # Initialize Brain Storage
    brain = BrainMemory()
    brain.record_experience(
        event_type="SYSTEM_ONBOARDING",
        summary=f"Agent '{name}' initialized on {topo.os_name} with wake word '{wake_word}'.",
        status="SUCCESS",
        details={"os": topo.os_name, "ram_gb": topo.ram_total_gb}
    )

    console.print(Panel(
        f"[bold green]System Onboarding Complete![/bold green]\n\n"
        f"• Agent Name: [cyan]{name}[/cyan]\n"
        f"• Wake Word: [cyan]{wake_word}[/cyan]\n"
        f"• Memory DB: [dim]{brain.db_path}[/dim]\n"
        f"• Notes Vault: [dim]{brain.notes_dir}[/dim]\n\n"
        f"Ready to execute commands.",
        border_style="green"
    ))

if __name__ == "__main__":
    run_onboarding()
