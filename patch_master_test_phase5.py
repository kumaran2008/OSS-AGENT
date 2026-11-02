from pathlib import Path

target = Path("test_master_end_to_end_rooms.py")
code = target.read_text(encoding="utf-8")

old_conv = """    conv_engine = UnifiedAsyncEngine()
    conv_engine.rooms.workspace = master_ws"""

new_conv = """    conv_engine = UnifiedAsyncEngine()
    conv_engine.rooms.workspace = master_ws
    conv_engine.rooms.model_switcher = switcher"""

if old_conv in code:
    code = code.replace(old_conv, new_conv)
    target.write_text(code, encoding="utf-8")
    print("[✓] Synced switcher to conv_engine in test_master_end_to_end_rooms.py.")
