from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Update the context query to parse properties
old_context_block = """        # 2. Fetch Recent Context from GraphBrainDB
        recent_context = []
        try:
            with self.memory_graph._get_conn() as conn:
                rows = conn.execute(
                    "SELECT node_id FROM nodes ORDER BY updated_at DESC LIMIT 3"
                ).fetchall()
                recent_context = [r[0] for r in rows]
        except Exception:
            pass"""

new_context_block = """        # 2. Fetch Recent Context from GraphBrainDB (Hydrate semantic dialogue)
        recent_context = []
        try:
            with self.memory_graph._get_conn() as conn:
                rows = conn.execute(
                    "SELECT properties FROM nodes WHERE node_type = 'episodic' ORDER BY updated_at DESC LIMIT 2"
                ).fetchall()
                for (prop_str,) in rows:
                    if prop_str:
                        p = json.loads(prop_str)
                        recent_context.append(f"User: {p.get('utterance', '')} -> Hype: {p.get('response', '')}")
        except Exception:
            pass"""

if old_context_block in code:
    code = code.replace(old_context_block, new_context_block)

# 2. Ensure voice synthesis awaits async synthesis in HybridVoiceController
old_dispatch_call = "audio_event = self.voice_controller.synthesize_and_dispatch("
new_dispatch_call = "audio_event = await self.voice_controller.synthesize_and_dispatch_async("

if old_dispatch_call in code and "synthesize_and_dispatch_async" not in code:
    code = code.replace(old_dispatch_call, new_dispatch_call)

target.write_text(code, encoding="utf-8")
print("[✓] Context hydration and async dispatch hooked into engine_harness.py")
