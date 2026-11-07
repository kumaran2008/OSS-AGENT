from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.oryn.accessibility_engine import accessibility_engine
from agent.oryn.contracts import (
    AXTreeSnapshot,
    ChannelType,
    ComputerAction,
    CoordinateSpace,
    ExecutionDriver,
    ExecutionReceipt,
    OperationType,
)
from agent.oryn.runtime import oryn_runtime
from agent.oryn.vision_engine import vision_engine


class FrontierCUADriver(ExecutionDriver):
    """Stage 6 Multi-Provider Frontier Computer-Using Agent (CUA) Driver & Translator.

    Supports:
      - Anthropic `computer_20250124` and `computer_20241022` tool declarations & 15-action vocabulary
      - OpenAI Responses API `computer_call` action batches
      - Google Gemini `computer_use` (`0..1000` normalized coordinate space)
      - Dynamic Vision Model Selection from SQLite `universal_model_registry` (0 hardcoded models)
    """

    channel: ChannelType = "frontier_cua"

    ANTHROPIC_OP_MAP: Dict[str, OperationType] = {
        "left_click": "click",
        "double_click": "double_click",
        "triple_click": "triple_click",
        "right_click": "right_click",
        "middle_click": "middle_click",
        "mouse_move": "move",
        "left_click_drag": "drag",
        "left_mouse_down": "mouse_down",
        "left_mouse_up": "mouse_up",
        "type": "type",
        "key": "keypress",
        "hold_key": "hold_key",
        "scroll": "scroll",
        "wait": "wait",
        "screenshot": "screenshot",
        "cursor_position": "move",
    }

    @staticmethod
    def build_provider_tool_declarations(
        display_width_px: int = 1024,
        display_height_px: int = 768,
        display_number: int = 1,
    ) -> Dict[str, Dict[str, Any]]:
        """Generates official tool declarations for Anthropic, OpenAI, and Gemini CUA."""
        return {
            "anthropic_20250124": {
                "type": "computer_20250124",
                "name": "computer",
                "display_width_px": display_width_px,
                "display_height_px": display_height_px,
                "display_number": display_number,
            },
            "anthropic_20241022": {
                "type": "computer_20241022",
                "name": "computer",
                "display_width_px": display_width_px,
                "display_height_px": display_height_px,
                "display_number": display_number,
            },
            "openai_cua": {
                "type": "computer",
                "display_width": display_width_px,
                "display_height": display_height_px,
            },
            "gemini_computer_use": {
                "type": "computer_use",
                "environment": "browser",
                "enable_prompt_injection_detection": True,
            },
        }

    @classmethod
    def translate_provider_tool_call(
        cls,
        provider_format: str,
        raw_tool_input: Dict[str, Any],
        runtime_id: str = "workstation",
    ) -> ComputerAction:
        """Translates Anthropic tool_use, OpenAI computer_call, or Gemini function_call
        into ORYN's unified immutable ComputerAction with exact coordinate space metadata.
        """
        fmt = provider_format.lower()
        act_id = str(raw_tool_input.get("id") or raw_tool_input.get("call_id") or f"cua_{int(time.time() * 1000)}")

        if "anthropic" in fmt or "computer_202" in fmt:
            raw_act = str(raw_tool_input.get("action", "left_click")).lower()
            op: OperationType = cls.ANTHROPIC_OP_MAP.get(raw_act, "click")
            coord_list = raw_tool_input.get("coordinate")
            coords: Optional[Tuple[int, int]] = (
                (int(coord_list[0]), int(coord_list[1]))
                if isinstance(coord_list, (list, tuple)) and len(coord_list) >= 2
                else None
            )
            start_coord = raw_tool_input.get("start_coordinate")
            drag_to: Optional[Tuple[int, int]] = None
            if op == "drag" and start_coord and coords:
                drag_to = coords
                coords = (int(start_coord[0]), int(start_coord[1]))

            text_val = raw_tool_input.get("text")
            keys_tup: Tuple[str, ...] = (str(text_val),) if op in ("keypress", "hold_key") and text_val else ()
            wait_ms = int(float(raw_tool_input.get("duration", 0)) * 1000) if op == "wait" else 0
            scroll_amt = int(raw_tool_input.get("scroll_amount", 3))
            scroll_dir = str(raw_tool_input.get("scroll_direction", "down")).lower()
            s_delta = (0, scroll_amt if scroll_dir == "down" else (-scroll_amt if scroll_dir == "up" else 0))

            return ComputerAction(
                action_id=act_id,
                runtime_id=runtime_id,
                channel="frontier_cua",
                operation=op,
                coordinates=coords,
                drag_to_coordinates=drag_to,
                coordinate_space="SCALED_XGA_1024x768",
                source_image_size=(1024, 768),
                text=str(text_val) if op == "type" and text_val is not None else None,
                keys=keys_tup,
                scroll_delta=s_delta,
                wait_ms=wait_ms,
                payload={"provider_format": provider_format, "raw_input": raw_tool_input},
            )

        if "gemini" in fmt:
            raw_act = str(raw_tool_input.get("action") or raw_tool_input.get("name") or "click").lower()
            op = "double_click" if "double" in raw_act else ("type" if "type" in raw_act else ("navigate" if "nav" in raw_act else "click"))
            x_val = raw_tool_input.get("x")
            y_val = raw_tool_input.get("y")
            if x_val is None and isinstance(raw_tool_input.get("coordinate"), (list, tuple)):
                x_val, y_val = raw_tool_input["coordinate"][0], raw_tool_input["coordinate"][1]
            coords = (int(x_val), int(y_val)) if (x_val is not None and y_val is not None) else None
            return ComputerAction(
                action_id=act_id,
                runtime_id=runtime_id,
                channel="frontier_cua",
                operation=op,
                target_ref=raw_tool_input.get("url") or raw_tool_input.get("intent"),
                coordinates=coords,
                coordinate_space="GEMINI_NORMALIZED_1000",
                source_image_size=(1000, 1000),
                text=raw_tool_input.get("text"),
                payload={"provider_format": "gemini_computer_use", "raw_input": raw_tool_input},
            )

        # OpenAI CUA (`computer_call`) format
        actions_list = raw_tool_input.get("actions") or [raw_tool_input]
        first = actions_list[0] if actions_list else {}
        raw_type = str(first.get("type", "click")).lower()
        op_map: Dict[str, OperationType] = {
            "click": "click",
            "double_click": "double_click",
            "drag": "drag",
            "keypress": "keypress",
            "move": "move",
            "scroll": "scroll",
            "type": "type",
            "wait": "wait",
            "screenshot": "screenshot",
        }
        op = op_map.get(raw_type, "click")
        x_v, y_v = first.get("x"), first.get("y")
        coords = (int(x_v), int(y_v)) if (x_v is not None and y_v is not None) else None
        keys_list = first.get("keys") or []
        return ComputerAction(
            action_id=act_id,
            runtime_id=runtime_id,
            channel="frontier_cua",
            operation=op,
            coordinates=coords,
            coordinate_space="SCALED_XGA_1024x768",
            source_image_size=(1024, 768),
            text=first.get("text"),
            keys=tuple(str(k) for k in keys_list),
            scroll_delta=(int(first.get("scroll_x", 0)), int(first.get("scroll_y", 0))),
            wait_ms=int(first.get("ms", 0)),
            payload={"provider_format": "openai_cua", "raw_input": raw_tool_input},
        )

    async def discover(self, target_app_or_url: str) -> Dict[str, Any]:
        model_pick = jev_ai_brain.select_model_from_directory(
            transcript=f"Visual GUI computer use on {target_app_or_url}",
            domain="HIGH_STAKES_CODING_DEBUG",
            task_difficulty=0.85,
            jev_confidence=0.80,
            require_vision=True,
        )
        return {
            "channel": self.channel,
            "available": True,
            "selected_vision_model": model_pick["model_id"],
            "blended_cost_per_1m_usd": model_pick["blended_cost_per_1m"],
            "domain_quality": model_pick["domain_quality"],
            "supported_wire_formats": ["anthropic_20250124", "anthropic_20241022", "openai_cua", "gemini_computer_use"],
        }

    @fault_recorder.guard(subsystem="oryn.cua_provider")
    async def execute(self, action: ComputerAction) -> ExecutionReceipt:
        t0 = time.perf_counter()
        payload = action.payload or {}

        # If a raw provider tool call was passed in payload, translate it first
        if "provider_tool_call" in payload:
            fmt = str(payload.get("provider_format", "anthropic_20250124"))
            action = self.translate_provider_tool_call(
                provider_format=fmt,
                raw_tool_input=payload["provider_tool_call"],
                runtime_id=action.runtime_id,
            )

        # Dynamically select the optimal vision-capable model from universal_model_registry (0 hardcoded models)
        goal_desc = str(payload.get("user_goal") or action.target_ref or action.text or action.operation)
        vision_model_pick = jev_ai_brain.select_model_from_directory(
            transcript=goal_desc,
            domain="HIGH_STAKES_CODING_DEBUG",
            task_difficulty=0.85,
            jev_confidence=0.82,
            require_vision=True,
        )

        native_w, native_h = oryn_runtime.primary_runtime.display_dimensions
        if action.coordinates is not None:
            native_coords = action.remap_to_native_pixels(native_w, native_h)
        else:
            vis_rec = await vision_engine.execute(action)
            if vis_rec.status == "BLOCKED_POLICY":
                return vis_rec
            native_coords = tuple(vis_rec.output_data.get("native_coordinates", (native_w // 2, native_h // 2)))

        # Dispatch hardware input under the per-desktop mutex lock
        dispatched_Action = ComputerAction(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel="accessibility",
            operation=action.operation,
            coordinates=native_coords,
            coordinate_space="NATIVE_DESKTOP_PX",
            text=action.text,
            keys=action.keys,
            wait_ms=action.wait_ms,
        )
        async with oryn_runtime.desktop_session_lock(timeout_sec=3.0):
            hw_ok = accessibility_engine._dispatch_os_input(dispatched_Action, native_coords)

        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel=self.channel,
            status="COMPLETED",
            verified=True,
            duration_ms=dur,
            observed_evidence=(
                f"Stage-6 Frontier CUA [{vision_model_pick['model_id']}] executed {action.operation} "
                f"at native_px={native_coords} (from {action.coordinate_space}={action.coordinates})"
            ),
            output_data={
                "selected_vision_model": vision_model_pick["model_id"],
                "model_cost_per_1m_usd": vision_model_pick["blended_cost_per_1m"],
                "model_quality": vision_model_pick["domain_quality"],
                "source_coordinate_space": action.coordinate_space,
                "source_coordinates": action.coordinates,
                "remapped_native_coordinates": native_coords,
                "native_display_size": (native_w, native_h),
                "hardware_dispatched": hw_ok,
            },
        )

    async def verify(
        self,
        action: ComputerAction,
        receipt: ExecutionReceipt,
        pre_state: Optional[AXTreeSnapshot] = None,
    ) -> ExecutionReceipt:
        receipt.verified = receipt.status == "COMPLETED"
        return receipt

    async def recover(
        self,
        action: ComputerAction,
        failed_receipt: ExecutionReceipt,
    ) -> Optional[ComputerAction]:
        return None


cua_provider = FrontierCUADriver()
