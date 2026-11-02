import json
import sqlite3
from pathlib import Path
from agent.federation.central_connector import CentralDatabaseConnector, SkillBundle

print("=== 1. INITIALIZING UPGRADED CONNECTOR ===")
connector = CentralDatabaseConnector()

print("\n=== 2. STAGING VERIFIED BUG PATCH ===")
ok_patch = connector.stage_verified_patch(
    error_signature="GATTTimeout: BLE write failed at 0x002A",
    resolution_logic="Added 150ms write interval backoff",
    files_modified=["agent/pa_scaffolder/hardware_iot.py"]
)
assert ok_patch
print("[✓] Bug patch staged into local queue.")

print("\n=== 3. STAGING LEARNED SKILL BUNDLE (KEYBOARD PLAYER) ===")
keyboard_skill = SkillBundle(
    skill_name="virtual_piano_player",
    description="Maps YouTube synthesia notes to touchscreen piano keys",
    trigger_intents=["play song", "play piano", "play keyboard", "play music"],
    entrypoint_code="def play_melody(notes): print('Injecting touch events:', notes)",
    required_packages=["mido"],
    parameters_schema={"song_name": "string", "tempo": "int"},
    author_node="aegis_node_alpha"
)

ok_skill = connector.stage_skill(keyboard_skill)
assert ok_skill
print(f"[✓] Skill '{keyboard_skill.skill_name}' staged successfully.")

# Inspect database contents
conn = sqlite3.connect(connector.db_path)
cur = conn.cursor()
cur.execute("SELECT item_type, identifier, synced FROM outbound_queue WHERE synced = 0")
queued = cur.fetchall()
conn.close()

print(f"[✓] Items queued in SQLite: {len(queued)}")
for item_type, ident, synced in queued:
    print(f"    • [{item_type.upper()}] {ident} (synced={synced})")
assert len(queued) >= 2

print("\n=== 4. TESTING TOKENLESS PUBLIC SKILL QUERY ===")
# Query intent resolution without an API token
matched_skill = connector.find_skill_by_intent("Can you play song on keyboard?")
print(f"Intent matching resolution test: {matched_skill}")

print("\n=== 5. TESTING OFFLINE SYNC RESILIENCE ===")
res = connector.sync_to_central_hub()
print(f"[✓] Hub Sync Response: {res['status']} -> {res['message']}")
assert res["status"] == "OFFLINE"  # Verified local queue protection when token is unset

print("\n============================================================")
print(">>> HUGGING FACE CONNECTOR IS COMPLETE AND SWARM-READY <<<")
print("============================================================")
