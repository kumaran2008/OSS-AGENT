from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add UniversalModelSwitcher import
if "from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher" not in code:
    code = "from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher\n" + code

# 2. Add switcher to RoomsEngine.__init__
old_init = "self.digest_engine = ResearchDigestEngine(self.research_memory, self.literature_engine)"
new_init = old_init + """
        self.model_switcher = UniversalModelSwitcher()
        self.model_switcher.sync_with_rooms_engine(self)"""

if old_init in code and "self.model_switcher =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add switch_model helper method to RoomsEngine
switcher_methods = """
    def switch_model_backend(self, target_room_or_task: str, backend_id: str) -> Tuple[bool, str]:
        \"\"\"Dynamically switches model for any room or task and hot-syncs MODE_REGISTRY.\"\"\"
        if target_room_or_task.lower() in [m.value for m in AgentMode]:
            ok, msg = self.model_switcher.switch_room_model(target_room_or_task, backend_id, rooms_engine=self)
            return ok, msg
        else:
            return self.model_switcher.switch_task_model(target_room_or_task, backend_id)
"""

if "def switch_model_backend" not in code:
    code = code + "\n" + switcher_methods

target.write_text(code, encoding="utf-8")
print("[✓] Integrated UniversalModelSwitcher into rooms_engine.py.")
