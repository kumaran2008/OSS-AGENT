from pathlib import Path

target = Path("agent/pa_scaffolder/model_router.py")
code = target.read_text(encoding="utf-8")

# 1. Add UniversalModelSwitcher import
if "from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher" not in code:
    code = "from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher\n" + code

# 2. Update ModelAgnosticRouter.__init__ to instantiate switcher
old_init = "self._load_registry()"
new_init = "self.switcher = UniversalModelSwitcher()\n        self._load_registry()"

if old_init in code and "self.switcher =" not in code:
    code = code.replace(old_init, new_init)

# 3. Update resolve_optimal_endpoint to read dynamically from switcher
old_resolve = """        pref_backend_id = self.preferences.get(profile.value)
        cfg = self.endpoints.get(pref_backend_id) if pref_backend_id else None"""

new_resolve = """        # Delegate to UniversalModelSwitcher
        ep_def = self.switcher.get_endpoint_for_task(profile)
        cfg = ModelEndpointConfig(
            backend_id=ep_def.backend_id,
            provider=ep_def.provider,
            model_name=ep_def.model_name,
            context_window=ep_def.context_window,
            cost_per_m_in=ep_def.cost_per_m_in,
            cost_per_m_out=ep_def.cost_per_m_out,
            api_base_url=ep_def.api_base_url,
            api_key_env_var=ep_def.api_key_env_var
        )"""

if old_resolve in code:
    code = code.replace(old_resolve, new_resolve)

target.write_text(code, encoding="utf-8")
print("[✓] Connected ModelAgnosticRouter to UniversalModelSwitcher.")
