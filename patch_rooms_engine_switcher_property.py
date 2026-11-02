from pathlib import Path
import re

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add model_switcher property with setter to RoomsEngine
property_code = """    @property
    def model_switcher(self) -> UniversalModelSwitcher:
        if not hasattr(self, "_model_switcher") or self._model_switcher is None:
            self._model_switcher = UniversalModelSwitcher()
        return self._model_switcher

    @model_switcher.setter
    def model_switcher(self, val: UniversalModelSwitcher):
        self._model_switcher = val
        if hasattr(self, "model_router") and self.model_router is not None:
            self.model_router.switcher = val
        val.sync_with_rooms_engine(self)
"""

if "@property\n    def model_switcher" not in code:
    anchor = "class RoomsEngine:"
    code = code.replace(anchor, anchor + "\n" + property_code)

# 2. Update __init__ to use the property setter cleanly
old_init_switcher = re.search(r'self\.model_switcher\s*=\s*UniversalModelSwitcher\(\)[^\n]*\n(?:\s*self\.model_switcher\.sync_with_rooms_engine\(self\)\n)?(?:\s*self\.model_router\.switcher\s*=\s*self\.model_switcher\n)?', code)
if old_init_switcher:
    code = code.replace(old_init_switcher.group(0), "self.model_switcher = UniversalModelSwitcher()\n")

target.write_text(code, encoding="utf-8")
print("[✓] Added synchronized model_switcher property to RoomsEngine.")
