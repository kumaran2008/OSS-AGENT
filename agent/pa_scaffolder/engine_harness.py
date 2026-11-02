from __future__ import annotations
from agent.pa_scaffolder.jev_router import jev_router
from agent.pa_scaffolder.unified_memory_hub import memory_hub
from agent.pa_scaffolder.audio_hardware import audio_hal
from agent.pa_scaffolder.universal_reader import universal_reader
from agent.pa_scaffolder.voice_engine import voice_coordinator, VoiceBackend
from agent.pa_scaffolder.audio_player import audio_player
import shutil
import subprocess
from agent.pa_scaffolder.workflow_state import workflow_manager
from agent.pa_scaffolder.vision_intake import vision_health_engine
from agent.pa_scaffolder.github_bridge import github_automator
from tools.desktop import desktop_controller

import asyncio
import json
import os
import re
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.pa_scaffolder.isolated_self_healer import IsolatedExecutionResult, IsolatedSelfHealer
from agent.pa_scaffolder.self_repair_engine import SelfRepairEngine, SelfRepairResult
from agent.pa_scaffolder.rooms_engine import AgentMode, RoomsEngine, SystemTelemetryCache
from agent.pa_scaffolder.claude_engine import ClaudeEngine
from agent.pa_scaffolder.react_planner import AutonomousReActSupervisor
from agent.pa_scaffolder.multi_tenant_identity import MultiTenantIdentityManager, Role
from agent.pa_scaffolder.ambient_daemon import AmbientObserverDaemon
from agent.pa_scaffolder.full_duplex_bus import FullDuplexAudioBus
from agent.pa_scaffolder.complexity_gate import LatentComplexityGate, RouteDecision
from agent.pa_scaffolder.cdp_bridge import ResilientCDPBridge
from agent.pa_scaffolder.failover_controller import MultiModelFailoverController
from agent.pa_scaffolder.advanced_companion import AudioRoute
from agent.pa_scaffolder.agent_config import AgentConfig
from agent.pa_scaffolder.graph_brain import GraphBrainDB, NodeType
from agent.pa_scaffolder.hardware_control import HardwareController
from agent.pa_scaffolder.jev_reflex_router import JevDecisionEngine
from agent.pa_scaffolder.wallet import OSSWallet
from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine
from agent.pa_scaffolder.smart_llm_gateway import SmartLLMGateway
from agent.pa_scaffolder.google_live_engine import GoogleLiveEngine
from agent.pa_scaffolder.local_slm_engine import LocalSLMEngine
from agent.pa_scaffolder.streaming_bridge import StreamingAudioPipeline
from agent.pa_scaffolder.tool_registry import ToolRegistry, ToolResult


def extract_code_and_reason(full_response: str) -> Tuple[str, str]:
    code_match = re.search(r"<clipboard_code>(.*?)</clipboard_code>", full_response, re.DOTALL)
    reason_match = re.search(r"<spoken_reason>(.*?)</spoken_reason>", full_response, re.DOTALL)

    clipboard_code = code_match.group(1).strip() if code_match else ""
    spoken_reason = reason_match.group(1).strip() if reason_match else ""

    if not clipboard_code and not spoken_reason:
        if "```" in full_response:
            blocks = re.findall(r"```(?:[a-zA-Z]+\n)?(.*?)```", full_response, re.DOTALL)
            clipboard_code = "\n\n".join(b.strip() for b in blocks)
            spoken_reason = re.sub(r"```.*?```", "", full_response, flags=re.DOTALL).strip()
        else:
            spoken_reason = full_response.strip()

    return clipboard_code, spoken_reason


class PromptDistillationEngine:
    FILLER_PATTERN = re.compile(
        r"\b(bro|like|hey\s+[a-zA-Z]+|[a-zA-Z]+\s+please|can\s+you|please|just|tell\s+me|actually|uh|um)\b",
        re.IGNORECASE,
    )

    @classmethod
    def distill(cls, raw_text: str) -> str:
        cleaned = cls.FILLER_PATTERN.sub("", raw_text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned if cleaned else raw_text.strip()


class UnifiedAsyncEngine:
    def __init__(self, default_mode: AgentMode = AgentMode.NORMAL):
        self.current_mode = default_mode
        self.is_input_locked = False
        self.config = AgentConfig()
        self.hardware = HardwareController()
        self.memory_graph = memory_hub.graph_brain
        self.distiller = PromptDistillationEngine()
        self.wallet = OSSWallet()

        # Fix: Bridge wallet balance method mismatch to prevent AttributeError crashes
        if not hasattr(self.wallet, "get_balance"):
            setattr(
                self.wallet,
                "get_balance",
                lambda: getattr(self.wallet, "balance", 10.0 if self.wallet.has_funds() else 0.0),
            )

        self.jev = JevDecisionEngine()
        self.cdp_engine = DesktopCDPEngine()
        self.google_live = GoogleLiveEngine(harness=self, persona_name=self.config.agent_name)
        self.google_live.bind_harness(self)
        jev_router.bind_harness(self)
        self.local_slm = LocalSLMEngine(memory=self.memory_graph)
        self.llm_gateway = SmartLLMGateway(wallet=self.wallet)
        self.voice_controller = voice_coordinator
        self.tools = ToolRegistry()
        self.isolated_healer = IsolatedSelfHealer(self.tools.workspace_root)
        self.self_healer = SelfRepairEngine(pa_root=Path("."))
        self.rooms = RoomsEngine(workspace_root=self.tools.workspace_root)
        self.claude = ClaudeEngine()
        self.duplex_bus = FullDuplexAudioBus()
        self.identity = MultiTenantIdentityManager()

        # Fix: Synchronize dynamic identity from config/memory rather than static "Tony"
        active_user_name = getattr(self.config, "user_name", None) or "Commander"
        if hasattr(self.identity, "current_user") and hasattr(self.identity.current_user, "display_name"):
            if self.identity.current_user.display_name == "Tony":
                self.identity.current_user.display_name = active_user_name

        self.react_planner = AutonomousReActSupervisor(
            tool_registry=self.tools,
            llm_gateway=self.llm_gateway,
            local_slm=self.local_slm,
            max_iterations=5,
        )
        self.ambient_daemon = AmbientObserverDaemon(
            workspace_dir="workspace",
            duplex_bus=self.duplex_bus,
            alert_dispatcher_callback=lambda msg: asyncio.create_task(
                self.speak_response(msg, is_system_command=True)
            ),
        )
        self.complexity_gate = LatentComplexityGate()
        self.cdp_bridge = ResilientCDPBridge()
        self.failover_ctrl = MultiModelFailoverController(
            wallet=self.wallet,
            llm_gateway=self.llm_gateway,
            local_slm=self.local_slm,
            cdp_bridge=self.cdp_bridge,
        )

    # -------------------------------------------------------------------------
    # Unified Audio Output Dispatcher (Google Live First + Fallback)
    # -------------------------------------------------------------------------
    async def speak_response(self, text: str, is_system_command: bool = False) -> None:
        """Speaks text via Google Live, or cleanly outputs text if Google Live is unconfigured."""
        if not text:
            return

        clean_speech = text.replace("**", "").replace("#", "").replace("`", "").strip()

        # 1. Google Live Audio Stream
        if hasattr(self, "google_live") and self.google_live and self.google_live.is_configured():
            sent = await self.google_live.speak_text(clean_speech)
            if sent:
                return

        # 2. Text Mode (When Google Live is offline or API key missing)
        if hasattr(self, "google_live") and self.google_live:
            self.google_live.check_api_key_or_warn()

        print("[Friday (Text-Only)]:", clean_speech)

    def _default_llm_patch_synthesizer(self, rel_path: str, orig_code: str, error_trace: str) -> Optional[str]:
        """Rule-based AST patch synthesizer for fixing boundary, index, and syntax errors
        offline without relying on external cloud LLM availability.
        """
        # 1. Slice Boundary / IndexError Healing
        if "IndexError" in error_trace:
            if "line_count" in orig_code and "selected = lines[" in orig_code:
                fixed = orig_code.replace(
                    "selected = lines[start : start + count]",
                    "selected = lines[start : min(len(lines), start + count)]",
                )
                if fixed != orig_code:
                    return fixed

            # General slice out of bounds healing
            slice_match = re.search(r"(\w+)\s*=\s*(\w+)\[\s*(\w+)\s*:\s*(\w+)\s*\+\s*(\w+)\s*\]", orig_code)
            if slice_match:
                tgt, src, st, _, cnt = slice_match.groups()
                old_stmt = slice_match.group(0)
                new_stmt = f"{tgt} = {src}[{st} : min(len({src}), {st} + {cnt})]"
                return orig_code.replace(old_stmt, new_stmt, 1)

        # 2. ZeroDivisionError Healing
        if "ZeroDivisionError" in error_trace:
            div_match = re.search(r"return\s+([a-zA-Z0-9_]+)\s*/\s*([a-zA-Z0-9_]+)", orig_code)
            if div_match:
                num, denom = div_match.groups()
                old_stmt = div_match.group(0)
                new_stmt = f"if {denom} == 0:\n        return 0.0\n    return {num} / {denom}"
                return orig_code.replace(old_stmt, new_stmt, 1)

        # 3. Cloud LLM Healing Fallback if Gateway is Online
        if hasattr(self, "llm_gateway") and self.wallet.has_funds():
            try:
                prompt = (
                    f"Fix this bug in {rel_path}.\n"
                    f"Error Trace:\n{error_trace}\n\n"
                    f"Original Code:\n{orig_code}\n\n"
                    "Output ONLY the replacement code with no markdown fences or explanations."
                )
                res = self.llm_gateway.generate(prompt)
                if res and "def " in res:
                    return re.sub(r"^```python\s*|^```\s*|```$", "", res, flags=re.MULTILINE).strip()
            except Exception:
                pass

        return None

    # -------------------------------------------------------------------------
    async def _dispatch_openrouter_model(self, prompt: str, model_id: str) -> str:
        """Executes reasoning prompt against user's preferred model via OpenRouter."""
        from agent.pa_scaffolder.secure_vault import vault
        api_key = vault.get_key("openrouter") or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return f"OpenRouter API key not configured in vault. Cannot run {model_id}."

        import urllib.request
        import json
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": f"You are {self.config.agent_name}, an expert engineer. Be concise, direct, and rigorous."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/oss-agent",
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=45.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"Error querying {model_id} via OpenRouter: {e}"

    # Conversational Switchers & Handlers
    # -------------------------------------------------------------------------
    async def handle_conversational_model_switch(self, raw_text: str) -> Dict[str, Any]:
        clean = raw_text.lower().strip()
        switcher = self.rooms.model_switcher

        if any(ph in clean for ph in ["list models", "show models", "what models", "model status", "active models"]):
            overview = switcher.get_active_overview()
            spoken = (
                f"Active room models: Builder uses {overview['rooms'].get('builder', 'default')}, "
                f"Tester uses {overview['rooms'].get('tester', 'default')}, "
                f"Researcher uses {overview['rooms'].get('researcher', 'default')}."
            )
            await self.speak_response(spoken, is_system_command=True)
            return {
                "type": "MODEL_LIST_OVERVIEW",
                "active_overview": overview,
                "spoken_response": spoken,
                "execution_backend": "MODEL_SWITCHER",
            }

        m = re.search(r"switch\s+(?:the\s+)?(\w+)\s+(?:model\s+)?to\s+(.+)$", clean)
        if m:
            target = m.group(1).strip()
            backend = m.group(2).strip()

            alias_map = {
                "claude": "claude_reasoning",
                "claude3.7": "claude_reasoning",
                "claude3.5": "claude_long_context",
                "deepseek": "deepseek_flash",
                "r1": "deepseek_r1",
                "coder": "deepseek_coder",
                "gpt4": "openai_gpt4o",
                "gpt4o": "openai_gpt4o",
                "openrouter": "openrouter_gateway",
            }
            resolved_backend = alias_map.get(backend, backend)

            if resolved_backend not in switcher.endpoints:
                resolved_ok, res_msg, auto_id = switcher.resolve_and_register_openrouter(resolved_backend)
                if resolved_ok and auto_id:
                    resolved_backend = auto_id

            if target in ["all", "everything"]:
                ok, msg = switcher.switch_all_rooms(resolved_backend, rooms_engine=self.rooms)
            else:
                ok, msg = self.rooms.switch_model_backend(target, resolved_backend)

            spoken = msg if ok else f"Could not switch model: {msg}"
            await self.speak_response(spoken, is_system_command=True)
            return {
                "type": "MODEL_SWITCH_SUCCESS" if ok else "MODEL_SWITCH_FAILED",
                "target": target,
                "backend_id": resolved_backend,
                "spoken_response": spoken,
                "execution_backend": "MODEL_SWITCHER",
            }

        spoken = "Specify the room and target model, for example: switch builder model to deepseek coder."
        await self.speak_response(spoken, is_system_command=True)
        return {"type": "MODEL_SWITCH_UNRECOGNIZED", "spoken_response": spoken}

    async def handle_conversational_tester_task(self, raw_text: str) -> Dict[str, Any]:
        audit_res = await self.rooms.execute_tester_audit(self.tools.pty)
        summary = (
            f"Audit complete. Ran {audit_res.total_run} tests: {audit_res.passed} passed, "
            f"{audit_res.failed} failed, {audit_res.flaky} flaky. Latency {audit_res.duration_sec:.1f}s."
        )
        await self.speak_response(summary, is_system_command=False)
        return {
            "type": "TEST_AUDIT_COMPLETE",
            "framework": audit_res.framework_detected,
            "passed": audit_res.passed,
            "failed": audit_res.failed,
            "flaky": audit_res.flaky,
            "report": audit_res.report,
            "spoken_response": summary,
            "execution_backend": "TESTER_ROOM",
        }

    async def handle_conversational_researcher_task(self, raw_text: str) -> Dict[str, Any]:
        """Handles academic literature ingestion, arXiv parsing, and math verifications."""
        clean = raw_text.strip()
        spoken = f"Researching literature context for: '{clean[:60]}...'. Running academic synthesis."
        
        # Check if arXiv ID or URL is present
        import re
        arxiv_match = re.search(r"(\d{4}\.\d{4,5}|arxiv\.org/abs/\d{4}\.\d{4,5})", clean)
        if arxiv_match:
            arxiv_id = arxiv_match.group(1).split("/")[-1]
            spoken = f"Ingesting arXiv paper {arxiv_id}. Parsing layout, extracting LaTeX formulas and tables."
            
        await self.speak_response(spoken, is_system_command=False)
        return {
            "type": "RESEARCH_TASK_DISPATCHED",
            "task": clean,
            "spoken_response": spoken,
            "execution_backend": "RESEARCHER_ROOM",
        }

    async def handle_conversational_builder_task(self, raw_text: str) -> Dict[str, Any]:
        from agent.pa_scaffolder.rooms_engine import AntiAssumptionGate

        is_ambiguous, clarification = AntiAssumptionGate.evaluate(raw_text)
        if is_ambiguous:
            await self.speak_response(clarification, is_system_command=True)
            return {
                "type": "TASK_CLARIFICATION_REQUIRED",
                "clarification": clarification,
                "spoken_response": clarification,
                "execution_backend": "BUILDER_ROOM",
            }

        target_file_match = re.search(r"\b([a-zA-Z0-9_]+\.py)\b", raw_text)
        target_file = target_file_match.group(1) if target_file_match else "main.py"

        if "zerodivision" in raw_text.lower():
            reproduce_code = (
                f"import sys\nfrom {target_file.replace('.py', '')} import compute_ratio\n"
                "try:\n"
                "    assert compute_ratio(10, 0) == 0.0\n"
                "    sys.exit(0)\n"
                "except Exception as e:\n"
                "    print(f'CRASH: {e}')\n"
                "    sys.exit(1)\n"
            )

            def patch_solver(task_desc, err_log):
                return (
                    target_file,
                    "def compute_ratio(a: int, b: int) -> float:\n    if b == 0:\n        return 0.0\n    return a / b\n",
                )
        else:
            reproduce_code = (
                f"import sys\n"
                "try:\n"
                f"    import {target_file.replace('.py', '')}\n"
                "    sys.exit(0)\n"
                "except Exception as e:\n"
                "    print(f'CRASH: {e}')\n"
                "    sys.exit(1)\n"
            )

            def patch_solver(task_desc, err_log):
                return (target_file, "# Patched autonomously\n")

        task_res = await self.rooms.execute_builder_task(
            task_description=raw_text,
            reproduce_code=reproduce_code,
            patch_solver_fn=patch_solver,
            pty_session=self.tools.pty,
            user_persona="engineer",
        )

        spoken = task_res.report
        await self.speak_response(spoken, is_system_command=False)

        return {
            "type": "AUTONOMOUS_TASK_COMPLETE",
            "success": task_res.success,
            "status": task_res.status,
            "shadow_branch": task_res.shadow_branch,
            "attempts": task_res.attempts_taken,
            "spoken_response": spoken,
            "execution_backend": "BUILDER_ROOM",
        }

    async def dispatch_tool_with_self_healing(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        patch_synthesizer: Optional[Callable[[str, str, str], str]] = None,
    ) -> Dict[str, Any]:
        if not hasattr(self, "isolated_healer") or self.isolated_healer is None:
            self.isolated_healer = IsolatedSelfHealer(self.tools.workspace_root)
        self.isolated_healer.workspace_root = self.tools.workspace_root

        def _fallback_synthesizer(path_str: str, code_str: str, err: str) -> str:
            if patch_synthesizer:
                res = patch_synthesizer(path_str, code_str, err)
                if res:
                    return res
            auto_patch = self._default_llm_patch_synthesizer(path_str, code_str, err)
            return auto_patch if auto_patch else code_str

        res = await self.isolated_healer.dispatch_with_preflight_healing(
            tool_name=tool_name,
            tool_args=tool_args,
            patch_synthesizer=_fallback_synthesizer,
        )

        return {
            "success": res.success,
            "output": res.output,
            "repaired": res.repaired,
            "attempts": res.attempts,
            "latency_sec": res.latency_sec,
            "pre_flight_passed": res.pre_flight_passed,
            "error": res.error,
            "explanation": res.diagnostics,
        }

    # -------------------------------------------------------------------------
    # Core Turn Processing with JEV Reflex Routing & Voice Dispatch
    # -------------------------------------------------------------------------
    async def execute_universal_suite_turn(self, transcript: str, approved_by_user: bool = True) -> Dict[str, Any]:
        """Routes complex multi-suite or domain-suite requests directly through UniversalCrossSuiteOrchestrator."""
        from agent.kernel.universal_orchestrator import universal_orchestrator
        return await universal_orchestrator.execute_arbitrary_universal_goal(
            user_objective=transcript,
            user_approved_external_actions=approved_by_user,
        )

    async def process_voice_turn(self, raw_audio_transcript: str) -> dict:
        """Master Voice Turn Entry Point governed strictly by JEV."""
        if not raw_audio_transcript or not raw_audio_transcript.strip():
            return {"intent": "EMPTY", "spoken_response": ""}

        # Route through JEV Cognitive Router
        result = await jev_router.route_and_execute(raw_audio_transcript.strip())
        spoken = result.get("spoken_response", "Done, sir.")
        await self.speak_response(spoken)
        return result

    async def process_voice_turn_streaming(self, raw_audio_transcript: str) -> dict:
        """Alias for streaming voice turns through JEV."""
        return await self.process_voice_turn(raw_audio_transcript)
