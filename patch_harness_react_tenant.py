from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add Imports
imports_to_add = """from agent.pa_scaffolder.react_planner import AutonomousReActSupervisor
from agent.pa_scaffolder.multi_tenant_identity import MultiTenantIdentityManager, Role
from agent.pa_scaffolder.ambient_daemon import AmbientObserverDaemon
"""
if "AutonomousReActSupervisor" not in code:
    code = imports_to_add + code

# 2. Add instances to __init__
old_init_anchor = "self.duplex_bus = FullDuplexAudioBus()"
new_init_anchor = """self.duplex_bus = FullDuplexAudioBus()
        self.identity = MultiTenantIdentityManager()
        self.react_planner = AutonomousReActSupervisor(
            tool_registry=self.tools,
            llm_gateway=self.llm_gateway,
            local_slm=self.local_slm,
            max_iterations=5
        )
        self.ambient_daemon = AmbientObserverDaemon(
            workspace_dir="workspace",
            duplex_bus=self.duplex_bus,
            alert_dispatcher_callback=lambda msg: asyncio.create_task(
                self.voice_controller.synthesize_and_dispatch_async(msg, is_system_command=True)
            )
        )"""

if old_init_anchor in code and "self.react_planner =" not in code:
    code = code.replace(old_init_anchor, new_init_anchor)

# 3. Intercept Switch User Spoken Commands
old_switch_check = "        # 1. State-Switching Commands"
new_switch_check = """        # 0. Multi-Tenant User Switching ("switch user to Alex", "who am i")
        lower_raw = raw_text.lower().strip()
        if lower_raw.startswith("switch user to ") or lower_raw.startswith("switch identity to "):
            target_user = lower_raw.split("to ")[-1].strip()
            ok, switch_msg = self.identity.switch_user(target_user)
            await self.voice_controller.synthesize_and_dispatch_async(switch_msg, is_system_command=True)
            return {
                "type": "TENANT_SWITCH",
                "active_user": self.identity.current_user.display_name,
                "spoken_response": switch_msg,
                "execution_backend": "IDENTITY_MANAGER"
            }

        if lower_raw in ["who am i", "current user", "profile"]:
            u = self.identity.current_user
            msg = f"You are logged in as {u.display_name} with {u.role.value.capitalize()} privileges."
            await self.voice_controller.synthesize_and_dispatch_async(msg, is_system_command=True)
            return {
                "type": "IDENTITY_STATUS",
                "active_user": u.display_name,
                "spoken_response": msg,
                "execution_backend": "IDENTITY_MANAGER"
            }

        # 1. State-Switching Commands"""

if old_switch_check in code and "TENANT_SWITCH" not in code:
    code = code.replace(old_switch_check, new_switch_check)

# 4. Add ReAct Multi-Step Interceptor before single-tool dispatch
old_cli_check = "        # 3. Direct Terminal Execution Check (Pillar 2: The Hands)"
new_react_check = """        # 2.9 Multi-Step Autonomous ReAct Planning Loop
        if any(lower_raw.startswith(p) for p in ["solve ", "diagnose ", "repair ", "fix and verify ", "auto fix "]):
            # Verify permission
            allowed, perm_err = self.identity.authorize_tool_action("bash_execute")
            if not allowed:
                resp = f"Access Denied: {perm_err}"
                await self.voice_controller.synthesize_and_dispatch_async(resp)
                return {"intent": "RBAC_RESTRICTION", "spoken_response": resp, "execution_backend": "RBAC_GATE"}

            react_res = await self.react_planner.execute_goal(
                goal=clean_text if clean_text else raw_text,
                user_id=self.identity.current_user.user_id
            )
            await self.voice_controller.synthesize_and_dispatch_async(react_res.final_summary)
            return {
                "intent": "AUTONOMOUS_REACT_LOOP",
                "spoken_response": react_res.final_summary,
                "execution_backend": "REACT_PLANNER_LOOP",
                "is_resolved": react_res.is_resolved,
                "steps": react_res.total_steps
            }

        # 3. Direct Terminal Execution Check (Pillar 2: The Hands)"""

if old_cli_check in code and "AUTONOMOUS_REACT_LOOP" not in code:
    code = code.replace(old_cli_check, new_react_check)

target.write_text(code, encoding="utf-8")
print("[✓] Integrated ReAct Supervisor, Multi-Tenant Identity, and Ambient Daemon into engine_harness.py")
