from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add import
if "from agent.pa_scaffolder.full_duplex_bus import FullDuplexAudioBus" not in code:
    code = "from agent.pa_scaffolder.full_duplex_bus import FullDuplexAudioBus\n" + code

# 2. Add duplex_bus to __init__
old_init_anchor = "self.tools = ToolRegistry()"
new_init_anchor = """self.tools = ToolRegistry()
        self.duplex_bus = FullDuplexAudioBus()"""

if old_init_anchor in code and "self.duplex_bus = FullDuplexAudioBus()" not in code:
    code = code.replace(old_init_anchor, new_init_anchor)

# 3. Pass duplex_bus to pipeline
old_pipeline_init = "pipeline = StreamingAudioPipeline(hal=self.voice_controller.audio_engine.hal, config=self.config)"
new_pipeline_init = "pipeline = StreamingAudioPipeline(hal=self.voice_controller.audio_engine.hal, config=self.config, duplex_bus=self.duplex_bus)"

if old_pipeline_init in code:
    code = code.replace(old_pipeline_init, new_pipeline_init)

target.write_text(code, encoding="utf-8")
print("[✓] Attached FullDuplexAudioBus to UnifiedAsyncEngine.")
