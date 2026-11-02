from __future__ import annotations
import sys
import json
from rich.console import Console
from oss_agent.config import load_settings
from oss_agent.jev_engine import JevDecisionEngine
from oss_agent.brain_memory import BrainMemory
from oss_agent.desktop_bridge import DesktopBridge

console = Console()

class AgentCore:
    """Master runtime binding user requests to Jev decision routing, brain memory, and desktop control."""

    def __init__(self):
        self.settings = load_settings()
        self.jev = JevDecisionEngine(api_key=self.settings.jev_api_key)
        self.brain = BrainMemory()
        self.desktop = DesktopBridge()

    def process_command(self, user_text: str) -> None:
        console.print(f"\n[bold green]User:[/bold green] {user_text}")

        # Step 1: Check for Ambiguous Entities (e.g. 'Call Kumar')
        tokens = user_text.split()
        for word in tokens:
            resolution = self.brain.resolve_entity(word)
            if resolution["status"] == "AMBIGUOUS":
                console.print(f"[bold yellow]{self.settings.agent_name}:[/bold yellow] {resolution['message']}")
                for idx, match in enumerate(resolution["matches"]):
                    console.print(f"  [{idx + 1}] {match['unique_handle']} ({match.get('disambiguation_rule', '')})")
                return

        # Step 2: Jev System-1 Routing & Action Classification
        possible_intents = ["DESKTOP_APP_ACTION", "RESEARCH_OR_CHAT", "SYSTEM_CONTROL", "PAYMENT_OR_ORDER"]
        decision = self.jev.decide_choice(
            state={"input": user_text, "agent": self.settings.agent_name},
            prompt="Classify the user intent into one of the designated action categories",
            options=possible_intents
        )

        console.print(f"[dim]Jev Decision: Intent = '{decision.selected_choice}' (Confidence: {decision.confidence * 100:.1f}%)[/dim]")

        # Step 3: Action Execution
        if decision.selected_choice == "DESKTOP_APP_ACTION":
            app_choice = self.jev.decide_choice(
                state={"input": user_text},
                prompt="Which application is targeted?",
                options=["Slack", "Zoom", "Google Chrome", "Terminal", "General App"]
            )
            console.print(f"Launching or focusing: [cyan]{app_choice.selected_choice}[/cyan]")
            self.desktop.launch_app(app_choice.selected_choice)

        elif decision.selected_choice == "PAYMENT_OR_ORDER":
            # Gated check via Jev Noul primitive
            safety_check = self.jev.decide_noul(
                state={"input": user_text},
                statement="Does this action require charging money, entering an OTP, or making a non-refundable payment?"
            )
            if safety_check.verdict:
                console.print(f"[bold red]Safety Gate:[/bold red] Payment/Financial action detected (Probability: {safety_check.probability:.2f}). Pausing for user confirmation.")
                return

        else:
            model = self.settings.task_model_mapping.get("general", "deepseek/deepseek-chat")
            console.print(f"Routing conversational or research task to: [bold magenta]{model}[/bold magenta]")

def main():
    agent = AgentCore()
    console.print(f"[bold cyan]{agent.settings.agent_name} Core Active.[/bold cyan] Type a command or 'exit':")
    while True:
        try:
            line = input("> ").strip()
            if not line or line.lower() in ["exit", "quit"]:
                break
            agent.process_command(line)
        except (KeyboardInterrupt, EOFError):
            break

if __name__ == "__main__":
    main()
