from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Add Pillar 3 Imports
p3_imports = """from agent.pa_scaffolder.complexity_gate import LatentComplexityGate, RouteDecision
from agent.pa_scaffolder.cdp_bridge import ResilientCDPBridge
from agent.pa_scaffolder.failover_controller import MultiModelFailoverController
"""
if "from agent.pa_scaffolder.complexity_gate import" not in code:
    code = p3_imports + code

# 2. Add Gate and Failover to __init__
old_init = "self.tools = ToolRegistry()"
new_init = """self.tools = ToolRegistry()
        self.complexity_gate = LatentComplexityGate()
        self.cdp_bridge = ResilientCDPBridge()
        self.failover_ctrl = MultiModelFailoverController(
            wallet=self.wallet,
            llm_gateway=self.llm_gateway,
            local_slm=self.local_slm,
            cdp_bridge=self.cdp_bridge
        )"""

if old_init in code and "self.complexity_gate" not in code:
    code = code.replace(old_init, new_init)
    print("[✓] Initialized ComplexityGate and FailoverController in engine_harness.py")

# 3. Intercept Tier 0 Micro-Reflexes at the start of process_voice_turn_streaming
old_cli_check = "        # 3. Direct Terminal Execution Check (Pillar 2: The Hands)"
new_tier0_check = """        # -------------------------------------------------------------
        # 2.5 TIER 0 MICRO-REFLEX GATE (<15ms Latency Path)
        # -------------------------------------------------------------
        route_decision = self.complexity_gate.route(
            clean_text if clean_text else raw_text,
            budget_available=self.wallet.has_funds(),
            preferred_backend=self.config.active_backend
        )

        if route_decision.tier == 0:
            tag = route_decision.action_tag
            if tag == "ABORT":
                resp = "Action aborted."
            elif tag == "AUDIO_MUTE":
                resp = "Audio muted."
            elif tag == "SYS_STATUS":
                resp = f"All systems nominal. Active engine: {self.config.active_backend}."
            else:
                resp = f"Executed {tag} reflex."
            await self.voice_controller.synthesize_and_dispatch_async(resp, is_system_command=True)
            return {
                "intent": "MICRO_REFLEX",
                "tier": 0,
                "action_tag": tag,
                "spoken_response": resp,
                "execution_backend": "TIER_0_MICRO_REFLEX"
            }

        # 3. Direct Terminal Execution Check (Pillar 2: The Hands)"""

if old_cli_check in code and "TIER 0 MICRO-REFLEX GATE" not in code:
    code = code.replace(old_cli_check, new_tier0_check)
    print("[✓] Wired Tier 0 Micro-Reflex path into engine_harness.py")

target.write_text(code, encoding="utf-8")
print("[✓] engine_harness.py successfully integrated with Pillar 3.")
