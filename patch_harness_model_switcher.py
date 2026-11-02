from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add model switcher conversational handler to UnifiedAsyncEngine
switcher_handler = """    async def handle_conversational_model_switch(self, raw_text: str) -> Dict[str, Any]:
        \"\"\"
        Handles natural voice commands for switching models on the fly:
        e.g., 'switch builder model to deepseek_coder', 'show models', 'list models'
        \"\"\"
        clean = raw_text.lower().strip()
        switcher = self.rooms.model_switcher

        # 1. Listing models
        if any(ph in clean for ph in ["list models", "show models", "what models", "model status", "active models"]):
            overview = switcher.get_active_overview()
            spoken = f"Active room models: Builder uses {overview['rooms'].get('builder', 'default')}, Tester uses {overview['rooms'].get('tester', 'default')}, Researcher uses {overview['rooms'].get('researcher', 'default')}."
            await self.voice_controller.synthesize_and_dispatch_async(spoken, is_system_command=True)
            return {
                "type": "MODEL_LIST_OVERVIEW",
                "active_overview": overview,
                "spoken_response": spoken,
                "execution_backend": "MODEL_SWITCHER"
            }

        # 2. Switching room or task model
        # Pattern match: 'switch <target> [model] to <backend_id>'
        m = re.search(r"switch\s+(?:the\s+)?(\w+)\s+(?:model\s+)?to\s+([a-zA-Z0-9_\-\.]+)", clean)
        if m:
            target = m.group(1).strip()
            backend = m.group(2).strip()

            # Normalize common colloquial backend aliases
            alias_map = {
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
                ok, msg = self.rooms.switch_model_backend(target, resolved_backend)

            spoken = msg if ok else f"Could not switch model: {msg}"
            await self.voice_controller.synthesize_and_dispatch_async(spoken, is_system_command=True)
            return {
                "type": "MODEL_SWITCH_SUCCESS" if ok else "MODEL_SWITCH_FAILED",
                "target": target,
                "backend_id": resolved_backend,
                "spoken_response": spoken,
                "execution_backend": "MODEL_SWITCHER"
            }

        # Default fallback
        spoken = "Specify the room and target model, for example: switch builder model to deepseek coder."
        await self.voice_controller.synthesize_and_dispatch_async(spoken, is_system_command=True)
        return {"type": "MODEL_SWITCH_UNRECOGNIZED", "spoken_response": spoken}
"""

if "def handle_conversational_model_switch" not in code:
    code = code.replace("class UnifiedAsyncEngine:", "class UnifiedAsyncEngine:\n" + switcher_handler)

# 2. Add conversational interceptor hook right at the top of process_voice_turn_streaming
model_switch_hook = """        # -------------------------------------------------------------
        # DYNAMIC MODEL SWITCHER CONVERSATIONAL INTERCEPTOR
        # -------------------------------------------------------------
        if any(phrase in raw_text.lower() for phrase in ["switch model", "change model", "list models", "show models", "active models"]) or (raw_text.lower().startswith("switch ") and " to " in raw_text.lower()):
            return await self.handle_conversational_model_switch(raw_text)
"""

if "DYNAMIC MODEL SWITCHER CONVERSATIONAL INTERCEPTOR" not in code:
    anchor = "        # ROOMS ENGINE MASTER INTERCEPTORS"
    if anchor in code:
        code = code.replace(anchor, model_switch_hook + "\n        # ROOMS ENGINE MASTER INTERCEPTORS")

target.write_text(code, encoding="utf-8")
print("[✓] Added Conversational Model Switcher handler and interceptor to engine_harness.py.")
