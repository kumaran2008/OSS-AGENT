from agent.chat_interface import AutonomousChatBot
from pathlib import Path
import json

bot = AutonomousChatBot()

print("=== 1. TEST CHATBOT COMMAND: BUILD PERSONAL AGENT ===")
response = bot.reply("Hey oss-agent, build personal agent named AegisCompanion with laser-focused builder style")
print(response)

# Verify the artifact was physically created on disk
pa_dir = Path.home() / ".personal_agent"
assert (pa_dir / "config.json").exists(), "PA config.json missing!"
assert (pa_dir / "memory" / "brain.db").exists(), "PA brain.db missing!"
assert (pa_dir / "pa").exists(), "PA launcher script missing!"

with open(pa_dir / "config.json") as f:
    cfg = json.load(f)
assert cfg["persona"]["name"] == "AegisCompanion"
assert cfg["persona"]["tone_style"] == "Laser-focused Builder"

print("\n[✓] Chatbot autonomously provisioned PA on disk with zero external API calls!")
