from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

old_init = "self.model_switcher = UniversalModelSwitcher()\n        self.model_switcher.sync_with_rooms_engine(self)"
new_init = """self.model_switcher = UniversalModelSwitcher()
        self.model_switcher.sync_with_rooms_engine(self)
        self.model_router.switcher = self.model_switcher"""

if old_init in code:
    code = code.replace(old_init, new_init)
    target.write_text(code, encoding="utf-8")
    print("[✓] Connected RoomsEngine.model_router to model_switcher.")
else:
    print("[i] RoomsEngine already connects model_router to model_switcher.")
