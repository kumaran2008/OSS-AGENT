from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add ToolRegistry Import
if "from agent.pa_scaffolder.tool_registry import ToolRegistry, ToolResult" not in code:
    code = "from agent.pa_scaffolder.tool_registry import ToolRegistry, ToolResult\n" + code

# 2. Add self.tools initialization to __init__
old_init_tail = "self.voice_controller = HybridVoiceController(wallet=self.wallet, session_spend_limit=1.00)"
new_init_tail = """self.voice_controller = HybridVoiceController(wallet=self.wallet, session_spend_limit=1.00)
        self.tools = ToolRegistry()"""

if old_init_tail in code and "self.tools = ToolRegistry()" not in code:
    code = code.replace(old_init_tail, new_init_tail)
    print("[✓] Initialized ToolRegistry inside UnifiedAsyncEngine.__init__")

# 3. Add Autonomous Tool Execution Branch to process_voice_turn_streaming
old_builder_check = """        if intent == "HARDWARE_OS_SETTING":
            _, resp = self.hardware.execute_hardware_command(raw_text)
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {"intent": intent, "spoken_response": resp, "execution_backend": "HARDWARE_OS_CONTROLLER"}"""

new_builder_check = """        if intent == "HARDWARE_OS_SETTING":
            _, resp = self.hardware.execute_hardware_command(raw_text)
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {"intent": intent, "spoken_response": resp, "execution_backend": "HARDWARE_OS_CONTROLLER"}

        # AUTONOMOUS TASK EXECUTION INTERCEPTOR (Pillar 2: The Hands)
        if intent == "CODE_BUILDER_TASK" and any(k in clean_text.lower() for k in ["run", "test", "build", "execute"]):
            # Direct CLI dispatch through sandbox
            cli_cmd = clean_text.lower()
            for prefix in ["run ", "execute ", "test "]:
                if cli_cmd.startswith(prefix):
                    cli_cmd = cli_cmd[len(prefix):]
            code, out = await self.tools.sandbox.execute_and_collect(cli_cmd, timeout=30.0)
            preview = out.strip().splitlines()[-1] if out.strip() else "Process completed with no output."
            resp = f"Executed {cli_cmd}. Exit code {code}. {preview}"
            await self.voice_controller.synthesize_and_dispatch_async(resp)
            return {
                "intent": intent,
                "spoken_response": resp,
                "execution_backend": "SANDBOX_PTY_EXEC",
                "exit_code": code
            }"""

if old_builder_check in code and "AUTONOMOUS TASK EXECUTION INTERCEPTOR" not in code:
    code = code.replace(old_builder_check, new_builder_check)
    print("[✓] Attached autonomous PTY sandbox executor into routing engine.")

target.write_text(code, encoding="utf-8")
print("[✓] engine_harness.py successfully integrated with Pillar 2.")
