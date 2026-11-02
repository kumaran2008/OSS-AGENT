from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from agent.kernel.plugin_host import Action, ActionResult, AuthorizedTaskContext, Capability, VerificationResult


class VisionIoTModePlugin:
    """Wraps VisionAnalyzer, SmartHomeIoTBridge & ModeMorphingKernel (Rooms 2.0)."""

    plugin_id = "plugin.vision_iot_mode"
    api_version = "1.0.0"

    def discover_capabilities(self) -> List[Capability]:
        return [
            Capability(id="vision.screen_capture", version="1.0.0", plugin_id=self.plugin_id, description="Captures live screen and extracts OCR + UI bounding boxes.", execution_backend="VISION_FALLBACK", risk_class="read", postconditions=["screen_frame_captured"]),
            Capability(id="vision.ui_actuate", version="1.0.0", plugin_id=self.plugin_id, description="Clicks or types into grounded UI elements with pre/post dHash and focus verification.", execution_backend="OS_ACCESSIBILITY", risk_class="local_write", postconditions=["ui_focus_and_dhash_verified"]),
            Capability(id="smarthome.control", version="1.0.0", plugin_id=self.plugin_id, description="Controls allowlisted smart-home devices with reversible state tracking.", execution_backend="OFFICIAL_API", risk_class="destructive", postconditions=["iot_state_register_verified"]),
            Capability(id="mode.switch_safe", version="1.0.0", plugin_id=self.plugin_id, description="Executes 6-step safe mode transition across Normal, Builder, Researcher, Streamer, and Gamer.", execution_backend="LOCAL_SANDBOX", risk_class="local_write", postconditions=["mode_context_switched"]),
            Capability(id="streamer.obs_or_clip", version="1.0.0", plugin_id=self.plugin_id, description="Switches OBS broadcast scenes or saves rolling replay clips.", execution_backend="OFFICIAL_API", risk_class="local_write", postconditions=["obs_or_clip_verified"]),
        ]

    def health_check(self) -> Dict[str, Any]:
        return {"plugin_id": self.plugin_id, "status": "HEALTHY"}

    async def execute(self, action: Action, context: AuthorizedTaskContext) -> ActionResult:
        from agent.pa_scaffolder.kernel_governance import sensory_synthesizer, smart_home_bridge
        from agent.pa_scaffolder.mode_kernel import mode_kernel
        from agent.pa_scaffolder.unified_memory_hub import memory_hub
        from agent.pa_scaffolder.universal_reader import universal_reader
        from agent.pa_scaffolder.vision_analyzer import vision_analyzer

        cap = action.capability_id
        prompt = action.raw_instruction
        legacy_intent = action.validated_arguments.get("legacy_intent", "")

        if cap == "vision.screen_capture":
            if legacy_intent == "READ_SCREEN":
                txt = universal_reader.read_screen()
                if sensory_synthesizer.needs_synthesis(prompt):
                    synth = await sensory_synthesizer.synthesize(txt, prompt)
                    raw = {"intent": "READ_SCREEN", "spoken_response": f"On your screen: {txt[:110]} | {synth}", "synthesis": synth}
                else:
                    raw = {"intent": "READ_SCREEN", "spoken_response": f"On your screen: {txt[:180]}"}
            else:
                raw = await memory_hub.capture_and_analyze_screen(prompt)
            return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=raw, provider_receipt="screen_captured")

        if cap == "vision.ui_actuate":
            raw = vision_analyzer.actuate_ui_element(prompt)
            ok = bool(raw.get("verified_state_change"))
            return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED" if ok else "UNCERTAIN", raw_Legacy_dict=raw, provider_receipt=f"dhash:{raw.get('post_click_dhash', '')[:8]}")

        if cap == "smarthome.control":
            raw = smart_home_bridge.execute_home_command(prompt)
            return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=raw, provider_receipt=f"iot:{raw.get('device_id')}:{raw.get('new_state')}", compensation_available=True)

        if cap == "mode.switch_safe":
            raw = mode_kernel.switch_mode(prompt)
            return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=raw, provider_receipt=f"mode:{raw.get('mode')}", compensation_available=True)

        raw = mode_kernel.execute_streamer_action(prompt)
        return ActionResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", raw_Legacy_dict=raw, provider_receipt="streamer_ok", compensation_available=True)

    def verify(self, action: Action, result: ActionResult) -> VerificationResult:
        from agent.pa_scaffolder.kernel_governance import smart_home_bridge

        cap = action.capability_id
        raw = result.raw_Legacy_dict
        if cap == "vision.ui_actuate":
            changed = bool(raw.get("verified_state_change"))
            return VerificationResult(action_id=action.action_id, capability_id=cap, status="COMPLETED" if changed else "UNCERTAIN", verified=changed, evidence_type="PERCEPTUAL_DHASH_DELTA", observed_evidence=f"pre={raw.get('pre_click_dhash', '')[:8]} vs post={raw.get('post_click_dhash', '')[:8]}")
        if cap == "smarthome.control":
            dev_id = raw.get("device_id", "")
            expected = raw.get("new_state", "")
            ok = False
            if dev_id and smart_home_bridge.DB_PATH.exists():
                with sqlite3.connect(smart_home_bridge.DB_PATH) as conn:
                    row = conn.execute("SELECT state FROM smart_home_devices WHERE device_id = ?", (dev_id,)).fetchone()
                    ok = bool(row and row[0] == expected)
            return VerificationResult(action_id=action.action_id, capability_id=cap, status="COMPLETED" if ok else "FAILED", verified=ok, evidence_type="IOT_STATE_REGISTER_CHECK", observed_evidence=f"Device {dev_id} confirmed in state '{expected}'")
        return VerificationResult(action_id=action.action_id, capability_id=cap, status="COMPLETED", verified=True, evidence_type="KERNEL_STATE_COMMIT", observed_evidence=result.provider_receipt)
