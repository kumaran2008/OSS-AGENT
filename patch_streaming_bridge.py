from pathlib import Path

target = Path("agent/pa_scaffolder/streaming_bridge.py")
code = target.read_text(encoding="utf-8")

old_init = """        chunker = SentenceStreamChunker(
            mode=self.config.streaming_mode,
            min_first_words=self.config.data.get("first_chunk_min_words", 3)
        )"""

new_init = """        mode = getattr(self.config, "streaming_mode", "adaptive")
        min_words = 3
        if hasattr(self.config, "data") and isinstance(self.config.data, dict):
            min_words = self.config.data.get("first_chunk_min_words", 3)
        chunker = SentenceStreamChunker(mode=mode, min_first_words=min_words)"""

if old_init in code:
    code = code.replace(old_init, new_init)
    target.write_text(code, encoding="utf-8")
    print("[✓] Patched streaming_bridge.py with safe attribute fallbacks")
else:
    print("[i] streaming_bridge.py already contains defensive fallbacks")
