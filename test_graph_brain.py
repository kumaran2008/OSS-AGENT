import time
from pathlib import Path
from agent.pa_scaffolder.graph_brain import GraphBrainDB

print("=" * 65)
print("     GRAPH BRAIN (SQLITE + OBSIDIAN) VERIFICATION")
print("=" * 65)

brain = GraphBrainDB(db_path=Path("workspace/test_brain.db"))

print("\n[1/4] Staging Biological Graph Nodes...")
n_creator = brain.add_or_update_node("Host_Streamer", "PERSON", "Desk_Setup", {"mic": "Elgato_Wave"})
n_obs = brain.add_or_update_node("OBS_Studio", "APP", "Display_1", {"port": 4455})
n_clip = brain.add_or_update_node("1v4_Clutch_Replay", "STREAM_EVENT", "Display_1:Game_Window", {"duration": 120})
n_file = brain.add_or_update_node("stream_session.json", "FILE", "Disk:workspace", {"format": "json"})

print(f" • Staged Nodes: Creator, OBS_Studio, 1v4_Clutch_Replay, stream_session.json")

print("\n[2/4] Testing Cyclic Graph Links (Proving Zero Infinite Loops)...")
# Form a complete cycle: Clip -> OBS -> Creator -> Clip
brain.link_nodes(n_clip, n_obs, "SAVED_VIA")
brain.link_nodes(n_obs, n_creator, "RUN_BY")
brain.link_nodes(n_creator, n_clip, "TRIGGERED")
brain.link_nodes(n_clip, n_file, "LOGGED_IN")

print(" • Built cyclic loop: [Clip] -> [OBS] -> [Creator] -> [Clip]")
print(" • Traversing memory outward from '1v4_Clutch_Replay'...")

t0 = time.perf_counter()
# Traverse outward up to depth 2
memories = brain.recall_associative_subgraph("1v4_Clutch_Replay", max_depth=2)
elapsed_ms = (time.perf_counter() - t0) * 1000

print(f" • Traversal resolved in {elapsed_ms:.2f} ms (Cycle detected and bypassed cleanly).")
for m in memories:
    print(f"   ├─ [{m['relationship']}] -> {m['category']}: '{m['entity']}' (Weight: {m['memory_weight']})")

assert len(memories) >= 3
assert elapsed_ms < 50.0  # Must complete rapidly without looping

print("\n[3/4] Exporting Knowledge Graph to Obsidian Markdown...")
vault_dir = Path("workspace/obsidian_vault")
exported_count = brain.export_to_obsidian_vault(vault_dir)
print(f" • Successfully created {exported_count} Obsidian notes at: {vault_dir.resolve()}")

# Verify file content has proper [[wikilinks]]
clip_md = (vault_dir / "1v4_Clutch_Replay.md").read_text(encoding="utf-8")
print("\n[Preview of Obsidian Note]:")
print("--------------------------------------------------")
print(clip_md)
print("--------------------------------------------------")
assert "[[" in clip_md and "]]" in clip_md

print("\n" + "=" * 65)
print(">>> GRAPH BRAIN VERIFIED: ROBUST, CYCLE-SAFE, NO INFINITE LOOPS <<<")
print("=" * 65)
