from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import websockets
except ImportError:
    websockets = None

from agent.pa_scaffolder.audio_hardware import audio_hal
from agent.pa_scaffolder.jev_router import jev_router
from agent.pa_scaffolder.secure_vault import vault


class GoogleLiveEngine:
    """Full-Duplex Audio Sensory Interface.
    Acts as the exclusive Ears (Mic stream) and Mouth (PCM playback) for the workstation.
    Delegates 100% of reasoning and execution to JEV.
    """

    WS_URI_TEMPLATE = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={key}"
    )

    def __init__(self, api_key: Optional[str] = None, harness: Optional[Any] = None, persona_name: str = "Friday"):
        self.api_key = api_key or vault.get_key("gemini") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.harness = harness
        self.persona_name = persona_name
        self.ws_connection: Optional[Any] = None
        self._warned_missing_key = False
        self._is_active = False

    def bind_harness(self, harness: Any) -> None:
        self.harness = harness
        jev_router.bind_harness(harness)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def check_api_key_or_warn(self) -> bool:
        if not self.is_configured():
            if not self._warned_missing_key:
                print("\n[!] Google Live API key is missing. Set GEMINI_API_KEY in environment or vault.db to enable voice.")
                print("    Operating smoothly in Text-Only Mode.\n")
                self._warned_missing_key = True
            return False
        return True

    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "consult_workstation_brain",
                "description": (
                    "CRITICAL: Delegates all user requests, coding tasks, terminal commands, "
                    "screen/file reading, and cooking workflows to JEV and the workstation brain."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "user_instruction": {"type": "STRING", "description": "The exact user prompt"}
                    },
                    "required": ["user_instruction"],
                },
            }
        ]

    # -------------------------------------------------------------------------
    # Upstream Audio Streamer (Microphone -> WebSocket)
    # -------------------------------------------------------------------------
    async def _stream_microphone_upstream(self, ws: Any) -> None:
        """Continuously streams 16kHz PCM audio frames to Gemini Live."""
        try:
            async for pcm_chunk in audio_hal.stream_mic_pcm(chunk_duration_sec=0.1):
                if not self._is_active:
                    break

                # If the chunk is non-empty, encode and transmit
                if pcm_chunk and any(pcm_chunk):
                    b64_data = base64.b64encode(pcm_chunk).decode("utf-8")
                    payload = {
                        "realtimeInput": {
                            "mediaChunks": [
                                {
                                    "mimeType": "audio/pcm;rate=16000",
                                    "data": b64_data,
                                }
                            ]
                        }
                    }
                    await ws.send(json.dumps(payload))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[!] Mic upstream streaming stopped: {e}")

    # -------------------------------------------------------------------------
    # Downstream Audio & Tool Receiver (WebSocket -> Audio HAL / JEV)
    # -------------------------------------------------------------------------
    async def _receive_downstream(self, ws: Any) -> None:
        """Listens for incoming 24kHz audio frames and tool calls from Gemini Live."""
        try:
            async for raw_msg in ws:
                event = json.loads(raw_msg)
                server_content = event.get("serverContent", {})

                # 1. Play incoming 24kHz audio frames directly
                model_turn = server_content.get("modelTurn", {})
                for part in model_turn.get("parts", []):
                    if "inlineData" in part and part["inlineData"].get("mimeType", "").startswith("audio/"):
                        pcm = base64.b64decode(part["inlineData"]["data"])
                        audio_hal.play_pcm_chunk(pcm, sample_rate=24000)

                # 2. Tool Calls -> Direct to JEV
                tool_call = event.get("toolCall")
                if tool_call:
                    responses = []
                    for call in tool_call.get("functionCalls", []):
                        call_id = call.get("id", "call_1")
                        args = call.get("args", {})
                        query = args.get("user_instruction", "")

                        # Delegate directly to JEV
                        result = await jev_router.route_and_execute(query)
                        out_text = result.get("spoken_response", "Done, sir.")
                        responses.append({"id": call_id, "response": {"output": out_text}})

                    await ws.send(json.dumps({"toolResponse": {"functionResponses": responses}}))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[!] Downstream receive loop ended: {e}")

    # -------------------------------------------------------------------------
    # Session Lifecycle
    # -------------------------------------------------------------------------
    async def speak_text(self, text: str) -> bool:
        """Sends text to Gemini Live for natural conversational audio synthesis."""
        if not self.check_api_key_or_warn() or not self.ws_connection:
            return False

        try:
            payload = {
                "clientContent": {
                    "turns": [{
                        "role": "user",
                        "parts": [{"text": f"Say this directly to the user with natural conversational wit: {text}"}]
                    }],
                    "turnComplete": True,
                }
            }
            await self.ws_connection.send(json.dumps(payload))
            return True
        except Exception:
            return False

    async def start_live_session(self) -> None:
        """Starts bidirectional, full-duplex session with parallel mic streaming."""
        if not self.check_api_key_or_warn():
            return
        if websockets is None:
            print("[!] 'websockets' library is required. Install with 'pip install websockets'.")
            return

        uri = self.WS_URI_TEMPLATE.format(key=self.api_key)
        system_instruction = (
            f"You are {self.persona_name}, an authentic, sharp workstation companion. "
            "You are strictly the voice and sensory interface. You DO NOT formulate your own answers or plans. "
            "For all user queries, advice, code, terminal actions, or tasks, you MUST call the `consult_workstation_brain` tool "
            "to retrieve JEV's finalized answer, then speak it naturally."
        )

        async with websockets.connect(uri) as ws:
            self.ws_connection = ws
            self._is_active = True

            # Handshake
            setup_payload = {
                "setup": {
                    "model": "models/gemini-2.0-flash-exp",
                    "generation_config": {"response_modalities": ["AUDIO"]},
                    "system_instruction": {"parts": [{"text": system_instruction}]},
                    "tools": [{"function_declarations": self.get_tool_declarations()}],
                }
            }
            await ws.send(json.dumps(setup_payload))
            _ = await ws.recv()

            # Launch parallel upstream and downstream tasks
            mic_task = asyncio.create_task(self._stream_microphone_upstream(ws))
            rx_task = asyncio.create_task(self._receive_downstream(ws))

            try:
                await asyncio.gather(mic_task, rx_task)
            finally:
                self._is_active = False
                mic_task.cancel()
                rx_task.cancel()
                audio_hal.close_playback_pipe()
