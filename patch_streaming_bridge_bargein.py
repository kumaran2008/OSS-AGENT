from pathlib import Path

target = Path("agent/pa_scaffolder/streaming_bridge.py")
code = target.read_text(encoding="utf-8")

# 1. Add FullDuplexAudioBus import
if "from agent.pa_scaffolder.full_duplex_bus import FullDuplexAudioBus" not in code:
    code = "from agent.pa_scaffolder.full_duplex_bus import FullDuplexAudioBus\n" + code

# 2. Update __init__ to accept full_duplex_bus
old_init = "    def __init__(self, hal: Optional[AdaptiveAudioHAL] = None, config: Optional[AgentConfig] = None):"
new_init = "    def __init__(self, hal: Optional[AdaptiveAudioHAL] = None, config: Optional[AgentConfig] = None, duplex_bus: Optional[FullDuplexAudioBus] = None):"

if old_init in code:
    code = code.replace(old_init, new_init)

old_init_body = "        self.config = config or AgentConfig()"
new_init_body = """        self.config = config or AgentConfig()
        self.duplex_bus = duplex_bus or FullDuplexAudioBus()"""

if old_init_body in code and "self.duplex_bus =" not in code:
    code = code.replace(old_init_body, new_init_body)

# 3. Add cancellation checks into run_pipeline
old_token_loop = """            async for token in token_stream:
                chunk = chunker.feed_token(token)
                if chunk:
                    synth_task = asyncio.create_task(synthesize_chunk_worker(chunk_idx, chunk))
                    synthesis_tasks.append((chunk_idx, chunk, synth_task))
                    chunk_idx += 1"""

new_token_loop = """            async for token in token_stream:
                if self.duplex_bus.is_interrupted:
                    break
                chunk = chunker.feed_token(token)
                if chunk:
                    synth_task = asyncio.create_task(synthesize_chunk_worker(chunk_idx, chunk))
                    synthesis_tasks.append((chunk_idx, chunk, synth_task))
                    chunk_idx += 1"""

if old_token_loop in code:
    code = code.replace(old_token_loop, new_token_loop)

old_playback_call = """                    if audio_file:
                        if on_first_audio_cb and chunk_idx == 0:
                            on_first_audio_cb()
                        self.hal.play_audio(audio_file, fallback_text=text)"""

new_playback_call = """                    if audio_file:
                        if self.duplex_bus.is_interrupted:
                            break
                        if on_first_audio_cb and chunk_idx == 0:
                            on_first_audio_cb()
                        # Register frame with AEC buffer
                        try:
                            raw_bytes = audio_file.read_bytes()
                            self.duplex_bus.write_speaker_frame(raw_bytes[:1600])
                        except Exception:
                            pass
                        self.hal.play_audio(audio_file, fallback_text=text)"""

if old_playback_call in code:
    code = code.replace(old_playback_call, new_playback_call)

target.write_text(code, encoding="utf-8")
print("[✓] Patched streaming_bridge.py with Full-Duplex AEC & Barge-In listeners.")
