from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add UniversalModelSwitcher import
if "from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher" not in code:
    code = "from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher\n" + code

# 2. Add switcher to ToolRegistry.__init__
old_init = "self.digest_engine = ResearchDigestEngine(self.research_memory, self.literature)"
new_init = old_init + "\n        self.model_switcher = UniversalModelSwitcher()"

if old_init in code and "self.model_switcher =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add dispatch handlers
old_dispatch = '            # -----------------------------------------------------------------\n            # Academic Writing, BibTeX & Daily Digest Tools'
new_dispatch = """            # -----------------------------------------------------------------
            # Universal Model Switcher & Registry Tools
            # -----------------------------------------------------------------
            if tool_name == "model_list_available":
                models = self.model_switcher.list_models()
                lines = [f"• {m['backend_id']} ({m['model_name']} via {m['provider']}) | Rooms: {m['assigned_rooms']}" for m in models]
                return ToolResult(tool_name=tool_name, success=True, output="\\n".join(lines))

            elif tool_name == "model_switch":
                target = args.get("target", "builder")
                backend = args.get("backend_id", "")
                if target in ["builder", "tester", "researcher", "normal", "streamer"]:
                    ok, msg = self.model_switcher.switch_room_model(target, backend)
                else:
                    ok, msg = self.model_switcher.switch_task_model(target, backend)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

            elif tool_name == "model_register_new":
                b_id = args.get("backend_id", "")
                prov = args.get("provider", "openai")
                m_name = args.get("model_name", "")
                ctx = int(args.get("context_window", 128000))
                c_in = float(args.get("cost_per_m_in", 1.0))
                c_out = float(args.get("cost_per_m_out", 3.0))
                base = args.get("api_base_url", "https://api.openai.com/v1")
                key_env = args.get("api_key_env_var")
                ok, msg = self.model_switcher.register_new_model(b_id, prov, m_name, ctx, c_in, c_out, base, key_env)
                return ToolResult(tool_name=tool_name, success=ok, output=msg, error=None if ok else msg)

"""

if "model_list_available" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch + old_dispatch)

# 4. Add schemas to get_all_tool_schemas
old_schema = '            {"type": "function", "function": {"name": "writer_reconcile_bibtex",'
new_schemas = """            {"type": "function", "function": {"name": "model_list_available", "description": "Lists all configured model endpoints and their room/task assignments", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "model_switch", "description": "Switches a PA room or task profile to use a different AI model backend", "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "backend_id": {"type": "string"}}, "required": ["target", "backend_id"]}}},
            {"type": "function", "function": {"name": "model_register_new", "description": "Registers a newly released AI model endpoint into the system", "parameters": {"type": "object", "properties": {"backend_id": {"type": "string"}, "provider": {"type": "string"}, "model_name": {"type": "string"}, "context_window": {"type": "integer"}, "api_base_url": {"type": "string"}}, "required": ["backend_id", "provider", "model_name"]}}},
"""

if "model_list_available" not in code and old_schema in code:
    code = code.replace(old_schema, new_schemas + old_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered Model Switcher tools in tool_registry.py.")
