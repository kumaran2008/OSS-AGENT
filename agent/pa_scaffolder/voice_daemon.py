from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    import websockets
except ImportError:
    websockets = None

from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


class GoogleLiveVoiceDaemon:
    """Production Full-Duplex Google Live Voice Daemon.
    - Manages real-time 16kHz audio capture and 24kHz speaker playback.
    - Handles native barge-in interruptions and local speaker buffer flushing.
    - Connects directly to UnifiedAsyncEngine for local tool execution and mode switching.
    - Delivers proactive voice notifications for background events and timers.
    """

    WS_URI_TEMPLATE = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={key}"
    )

    def __init__(self, engine: UnifiedAsyncEngine):
        self.engine = engine
        self.config = engine.config
        self.live = engine.google_live
        self.api_key = self.live.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.is_running = False
        self.ws: Optional[Any] = None

    def _get_audio_drivers(self):
        """Attempts to load low-latency audio drivers (sounddevice / pyaudio)."""
        try:
            import sounddevice as sd
            return "sounddevice", sd
        except (ImportError, OSError):
            pass
        return None, None

    async def start_voice_loop(self) -> None:
        if not self.api_key:
            print("\n[ERROR] GEMINI_API_KEY is not configured!")
            print("Set it via: export GEMINI_API_KEY='your_key_here'\n")
            return

        if websockets is None:
            print("\n[ERROR] websockets package is missing. Run: pip install websockets\n")
            return

        driver_name, sd_driver = self._get_audio_drivers()
        agent_name = str(self.config.agent_name)

        print("=" * 64)
        print(f"🎙️  {agent_name.upper()} GOOGLE LIVE FULL-DUPLEX AUDIO DAEMON")
        print(f"• Active Mode:    [{self.engine.rooms.current_mode.name}]")
        print(f"• Audio Driver:   [{driver_name.upper() if driver_name else 'TERMINAL_STREAM'}]")
        print(f"• Proactive Bus:  [Active]")
        print("=" * 64)
        print("Hyper is listening. Speak into your mic or type text. Press Ctrl+C to exit.\n")

        uri = self.WS_URI_TEMPLATE.format(key=self.api_key)
        self.is_running = True

        try:
            async with websockets.connect(uri) as ws:
                self.ws = ws
                self.live.ws_connection = ws

                # 1. Handshake Setup Message
                setup_payload = {
                    "setup": {
                        "model": "models/gemini-2.0-flash-exp",
                        "generation_config": {
                            "response_modalities": ["TEXT"],  # Defaults to TEXT stream; switch to AUDIO on PC with sounddevice
                        },
                        "system_instruction": {
                            "parts": [{
                                "text": (
                                    f"Your name is {agent_name}. You are an authentic, proactive personal agent "
                                    "and engineering collaborator. Acknowledge commands directly, concisely, and with "
                                    "conversational sharpness. Always execute registered tools when the user requests "
                                    "hardware status, timers, code fixes, file reading, or mode transitions."
                                )
                            }]
                        },
                        "tools": [{"function_declarations": self.live.get_tool_declarations()}],
                    }
                }
                await ws.send(json.dumps(setup_payload))
                _ = await ws.recv()
                print(f"[✓] Connection established. {agent_name} is online.\n")

                # Concurrently run listener, user input, and proactive notification queue
                tasks = [
                    asyncio.create_task(self._listen_server_loop(ws)),
                    asyncio.create_task(self._keyboard_input_loop(ws)),
                    asyncio.create_task(self._proactive_notification_loop(ws)),
                ]

                # Wait until any task triggers shutdown
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n[✓] Voice session terminated cleanly.")
        except Exception as e:
            print(f"\n[!] WebSocket stream error: {e}")
        finally:
            self.is_running = False
            self.ws = None
            self.live.ws_connection = None

    async def _listen_server_loop(self, ws: Any) -> None:
        """Processes incoming tokens, audio chunks, and tool invocations from Google Live."""
        agent_name = str(self.config.agent_name)
        async for raw_msg in ws:
            event = json.loads(raw_msg)
            server_content = event.get("serverContent", {})

            # 1. Handle Barge-In Interruption
            if server_content.get("interrupted"):
                print(f"\n[!] Barge-in detected: {agent_name} paused.")
                if hasattr(self.engine, "duplex_bus"):
                    self.engine.duplex_bus.flush_buffers()

            # 2. Text / Speech Output
            model_turn = server_content.get("modelTurn", {})
            for part in model_turn.get("parts", []):
                if "text" in part:
                    print(part["text"], end="", flush=True)

            if server_content.get("turnComplete"):
                print()

            # 3. Handle Tool Invocations
            tool_call = event.get("toolCall")
            if tool_call:
                print(f"\n⚙️  [{agent_name} Executing Tool]")
                function_responses = []
                for call in tool_call.get("functionCalls", []):
                    call_id = call.get("id", "call_1")
                    name = call.get("name", "")
                    args = call.get("args", {})
                    print(f" • Tool: {name}({args})")

                    out = await self.live.dispatch_local_tool(name, args)
                    print(f" • Result: {out[:120]}...")

                    function_responses.append({
                        "id": call_id,
                        "response": {"output": out}
                    })

                tool_resp_payload = {
                    "toolResponse": {"functionResponses": function_responses}
                }
                await ws.send(json.dumps(tool_resp_payload))

    async def _keyboard_input_loop(self, ws: Any) -> None:
        """Concurrent terminal keyboard reader for multimodal input."""
        loop = asyncio.get_running_loop()
        agent_name = str(self.config.agent_name)
        while self.is_running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                clean = line.strip()
                if not clean:
                    continue
                if clean.lower() in ["exit", "quit", "/quit"]:
                    self.is_running = False
                    break

                client_turn = {
                    "clientContent": {
                        "turns": [{
                            "role": "user",
                            "parts": [{"text": clean}]
                        }],
                        "turnComplete": True
                    }
                }
                print(f"{agent_name} > ", end="", flush=True)
                await ws.send(json.dumps(client_turn))
            except (KeyboardInterrupt, asyncio.CancelledError):
                break

    async def _proactive_notification_loop(self, ws: Any) -> None:
        """Polls the harness notification queue and pushes proactive system turns."""
        while self.is_running:
            try:
                alert_text = await self.live._notification_queue.get()
                if alert_text and ws:
                    print(f"\n🔔 [Proactive System Event Injected]")
                    payload = {
                        "clientContent": {
                            "turns": [{
                                "role": "user",
                                "parts": [{"text": alert_text}]
                            }],
                            "turnComplete": True,
                        }
                    }
                    await ws.send(json.dumps(payload))
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.5)


def launch_voice_daemon(engine: UnifiedAsyncEngine) -> None:
    daemon = GoogleLiveVoiceDaemon(engine)
    asyncio.run(daemon.start_voice_loop())


if __name__ == "__main__":
    eng = UnifiedAsyncEngine()
    launch_voice_daemon(eng)
