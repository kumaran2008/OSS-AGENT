from pathlib import Path
import re
import py_compile

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

helper_method = """    def get_current_backend(self) -> str:
        \"\"\"Returns the active model backend ID for the current mode.\"\"\"
        if hasattr(self, "model_switcher") and self.model_switcher:
            ep = self.model_switcher.get_endpoint_for_room(self.current_mode)
            return ep.backend_id if hasattr(ep, "backend_id") else str(ep)
        mode_cfg = self.REGISTRY.get(self.current_mode)
        return getattr(mode_cfg, "preferred_backend", "deepseek_flash")
"""

if "def get_current_backend" not in code:
    # Inject before the last line or before close/switch methods
    anchor = "    def switch_model_backend("
    if anchor in code:
        code = code.replace(anchor, helper_method + "\n" + anchor, 1)
    else:
        code += "\n" + helper_method

target.write_text(code, encoding="utf-8")
py_compile.compile(str(target), doraise=True)
print("[✓] Added get_current_backend() to RoomsEngine.")
