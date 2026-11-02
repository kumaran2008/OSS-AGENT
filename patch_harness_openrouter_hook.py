from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_snippet = """            alias_map = {
                "claude": "claude_reasoning",
                "claude3.7": "claude_reasoning",
                "claude3.5": "claude_long_context",
                "deepseek": "deepseek_flash",
                "r1": "deepseek_r1",
                "coder": "deepseek_coder",
                "ollama": "local_ollama",
                "local": "local_ollama",
                "gpt4": "openai_gpt4o",
                "gpt4o": "openai_gpt4o"
            }
            resolved_backend = alias_map.get(backend, backend)

            if target in ["all", "everything"]:
                ok, msg = switcher.switch_all_rooms(resolved_backend, rooms_engine=self.rooms)
            else:
                ok, msg = self.rooms.switch_model_backend(target, resolved_backend)"""

new_snippet = """            alias_map = {
                "claude": "claude_reasoning",
                "claude3.7": "claude_reasoning",
                "claude3.5": "claude_long_context",
                "deepseek": "deepseek_flash",
                "r1": "deepseek_r1",
                "coder": "deepseek_coder",
                "gpt4": "openai_gpt4o",
                "gpt4o": "openai_gpt4o",
                "openrouter": "openrouter_gateway"
            }
            resolved_backend = alias_map.get(backend, backend)

            # Check if backend needs OpenRouter dynamic resolution
            if resolved_backend not in switcher.endpoints:
                resolved_ok, res_msg, auto_id = switcher.resolve_and_register_openrouter(resolved_backend)
                if resolved_ok and auto_id:
                    resolved_backend = auto_id

            if target in ["all", "everything"]:
                ok, msg = switcher.switch_all_rooms(resolved_backend, rooms_engine=self.rooms)
            else:
                ok, msg = self.rooms.switch_model_backend(target, resolved_backend)"""

if old_snippet in code:
    code = code.replace(old_snippet, new_snippet)
    target.write_text(code, encoding="utf-8")
    print("[✓] Patched engine_harness.py with OpenRouter auto-discovery voice hook.")
else:
    print("[i] Hook already patched in engine_harness.py.")
