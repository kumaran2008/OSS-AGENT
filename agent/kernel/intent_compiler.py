from __future__ import annotations

import hashlib
import re
import shlex
import time
from typing import Any, Dict, List, Optional, Tuple

from agent.kernel.plugin_host import Action, plugin_host


class TypedIntentCompiler:
    """Zero-Regex-Cliff Hybrid Semantic & Schema-Guided Intent Compiler (Upgrade A).
    - Understands natural, emotional, or unscripted phrasing (e.g., "Bro I'm exhausted,
      something looks weird inside voice_engine.py, check what functions are inside it")
      by scoring capability schemas + semantic intent clusters when exact patterns miss.
    - Supports Typed Zero-Token Data-Flow Pipe bindings (`$step_1.output.field`).
    """

    INTENT_TO_CAPABILITY: Dict[str, str] = {
        "BUILDER_AST_INSPECT": "builder.ast_inspect",
        "BUILDER_PATCH_VERIFIED": "builder.patch_verified",
        "BUILDER_RECONCILE_CODE": "builder.reconcile_code",
        "BUILDER_PYTEST_SANDBOX": "builder.pytest_sandbox",
        "MCP_TOOL_CALL": "mcp.tool_invoke",
        "INSTAGRAM_OPEN_REELS": "instagram.open_reels",
        "CAPABILITY_TRUTH_LEDGER": "kernel.truth_ledger",
        "READ_DOCUMENT_SLICE": "doc.read_slice",
        "READ_BOOKMARK_CONTINUE": "doc.bookmark_continue",
        "BOOK_TOPIC_SEARCH": "doc.topic_jump",
        "WEB_SEARCH": "web.search_cited",
        "READ_YOUTUBE": "youtube.transcript_staged",
        "SEND_MESSAGE_REPLY": "messaging.send_confirmed",
        "READ_NOTIFICATIONS": "notifications.triage",
        "TEMPORAL_REMINDER": "schedule.reminder_create",
        "MEMORY_STORE": "memory.store_trusted",
        "MEMORY_RECALL": "memory.recall_graph",
        "SOCIAL_IDENTITY_ACTION": "social.household_manage",
        "HEALTH_NUTRITION_ACTION": "nutrition.log_or_query",
        "RESEARCH_ACTION": "research.digest_or_deadend",
        "PHOTO_SEARCH": "photo.vault_ops",
        "VISION_PHOTO_INGEST": "photo.vault_ops",
        "VISION_SCREEN_CAPTURE": "vision.screen_capture",
        "READ_SCREEN": "vision.screen_capture",
        "UI_ACTUATION": "vision.ui_actuate",
        "SMART_HOME_ACTION": "smarthome.control",
        "MODE_SWITCH": "mode.switch_safe",
        "MODEL_SWITCH_VOICE": "model.switch_voice",
        "STREAMER_ACTION": "streamer.obs_or_clip",
        "TERMINAL_ACTION": "builder.terminal_sandbox",
        "MULTI_AI_COUNCIL": "model.council_consensus",
        "FRONTIER_REASONING": "model.chat_routed",
    }

    CAPABILITY_TO_INTENT: Dict[str, str] = {v: k for k, v in INTENT_TO_CAPABILITY.items()}

    # Rich semantic concept clusters so natural speech without rigid keywords maps accurately
    SEMANTIC_CAPABILITY_LEXICON: Dict[str, List[str]] = {
        "builder.ast_inspect": ["function", "functions", "classes", "methods", "structure", "inside", "look inside", "check code", "symbols", "ast", "parse", "def "],
        "builder.reconcile_code": ["reconcile", "broken", "crashing", "failing", "fix", "repair", "solve", "until tests pass", "make it pass", "debug", "error in"],
        "builder.patch_verified": ["patch", "replace", "swap", "modify file", "change string", "update code"],
        "instagram.open_reels": ["reels", "instagram", "insta", "watch reels", "scroll reels", "short videos"],
        "youtube.transcript_staged": ["youtube", "youtu.be", "video transcript", "captions", "cooking video", "lecture video"],
        "mcp.tool_invoke": ["mcp", "github issues", "open issues", "pull requests", "repository issues", "langchain", "supermemory"],
        "messaging.send_confirmed": ["whatsapp", "text", "tell", "let him know", "let her know", "send message", "reply", "ping"],
        "doc.bookmark_continue": ["continue reading", "pick up where", "resume reading", "read next lines", "keep reading"],
        "doc.topic_jump": ["chapter", "section about", "where does the book", "find in book", "topic in"],
        "smarthome.control": ["lights", "thermostat", "ac", "air conditioner", "lock", "door", "living room", "bedroom"],
    }

    @staticmethod
    def tokenize_shell_safely(cmd_str: str) -> List[str]:
        try:
            return shlex.split(cmd_str, posix=True)
        except ValueError:
            return cmd_str.split()

    def infer_semantic_capability(self, utterance: str) -> Tuple[Optional[str], float]:
        """Scores natural-language utterances (including emotional/unscripted speech)
        against registered capability descriptions and semantic concept clusters.
        """
        lower = utterance.lower()
        has_py_file = bool(re.search(r"[a-zA-Z0-9_\-\./]+\.py\b", utterance))
        best_cap: Optional[str] = None
        best_score = 0.0

        for cap_id, phrases in self.SEMANTIC_CAPABILITY_LEXICON.items():
            score = 0.0
            for ph in phrases:
                if ph in lower:
                    score += 0.35 if " " in ph else 0.22
            if has_py_file and cap_id.startswith("builder."):
                if any(w in lower for w in ("function", "classes", "structure", "what is inside", "look inside", "check what")):
                    if cap_id == "builder.ast_inspect":
                        score += 0.55
                elif any(w in lower for w in ("fix", "broken", "crash", "error", "pass", "repair", "solve")):
                    if cap_id == "builder.reconcile_code":
                        score += 0.55
            if score > best_score:
                best_score = score
                best_cap = cap_id

        return (best_cap, round(best_score, 3)) if best_score >= 0.40 else (None, 0.0)

    def compile_single_action(
        self,
        raw_task: str,
        legacy_intent: str,
        pipe_ctx: Optional[Any] = None,
    ) -> Action:
        from agent.pa_scaffolder.blackboard_kernel import blackboard

        resolved_task = blackboard.resolve_deictics(raw_task, pipe_ctx=pipe_ctx)
        lower = resolved_task.lower().strip()

        if legacy_intent in self.INTENT_TO_CAPABILITY and legacy_intent not in ("FRONTIER_REASONING", "FAST_QUERY", ""):
            cap_id = self.INTENT_TO_CAPABILITY[legacy_intent]
        elif re.search(r"\b(?:capability\s+truth\s+ledger|show\s+truth\s+ledger|plugin\s+ledger)\b", lower):
            cap_id = "kernel.truth_ledger"
        elif legacy_intent == "MODEL_SWITCH_VOICE" or (
            re.search(r"\b(?:change\s+(?:model\s+)?to|switch\s+(?:ai\s+|model\s+)?to|use\s+model|set\s+model\s+to|reset\s+model\s+to\s+default)\b", lower)
            and any(m_kw in lower for m_kw in ("opus", "sonnet", "claude", "deepseek", "gemini", "gpt", "codex", "argon", "default"))
        ):
            cap_id = "model.switch_voice"
        elif re.search(r"\b(?:inspect\s+ast|ast\s+inspect|parse\s+ast|inspect\s+functions\s+in)\b", lower):
            cap_id = "builder.ast_inspect"
        elif re.search(r"\b(?:reconcile\s+code|reconcile\s+tests|auto[\s\-]repair|keep\s+tests\s+passing|fix\s+until\s+tests\s+pass)\b", lower):
            cap_id = "builder.reconcile_code"
        elif re.search(r"\b(?:mcp\s+server|mcp\s+tool|list\s+github\s+issues\s+via\s+mcp)\b", lower):
            cap_id = "mcp.tool_invoke"
        elif re.search(r"\b(?:verified\s+patch|apply\s+patch\s+to|self[\s\-]heal\s+file)\b", lower):
            cap_id = "builder.patch_verified"
        elif re.search(r"\b(?:play\s+instagram|open\s+instagram.*reels|go\s+to\s+reels|instagram\s+reels)\b", lower):
            cap_id = "instagram.open_reels"
        else:
            cap_id = self.INTENT_TO_CAPABILITY.get(legacy_intent, "legacy.jev_dispatch")
            # Upgrade A: If legacy regex fell back to generic chat, run semantic capability inference!
            if cap_id in ("model.chat_routed", "legacy.jev_dispatch"):
                sem_cap, sem_conf = self.infer_semantic_capability(resolved_task)
                if sem_cap and sem_conf >= 0.40:
                    cap_id = sem_cap
                    legacy_intent = self.CAPABILITY_TO_INTENT.get(sem_cap, legacy_intent)

        cap_meta = plugin_host.get_capability(cap_id)
        risk_class = cap_meta.risk_class if cap_meta else "read"
        sensitivity = cap_meta.data_sensitivity if cap_meta else "PUBLIC"
        preconds = list(cap_meta.preconditions) if cap_meta else []
        postconds = list(cap_meta.postconditions) if cap_meta else ["deterministic_verification_pass"]

        target = "workstation"
        args: Dict[str, Any] = {"prompt": resolved_task, "legacy_intent": legacy_intent}

        fm = re.search(r"([a-zA-Z0-9_\-\./]+\.(?:py|md|txt|json|pdf|docx|png|jpg|sh))", resolved_task)
        if fm:
            target = fm.group(1)
            args["file_path"] = target
            blackboard.active_file = target
        elif cap_id.startswith("builder.") and cap_id != "builder.terminal_sandbox":
            target = blackboard.active_file or "agent/pa_scaffolder/voice_engine.py"
            args["file_path"] = target

        if cap_id == "messaging.send_confirmed":
            m = re.search(
                r"(?:reply\s+to|message\s+to|msg\s+to|text\s+to|tell|ping)\s+([A-Za-z0-9_]+)(?:\s+on\s+([A-Za-z0-9_]+))?\s+(?:that|saying|:|with)\s+(.+)$",
                resolved_task.strip(),
                flags=re.I,
            )
            if m:
                target = m.group(1).strip().title()
                args["recipient"] = target
                args["app"] = (m.group(2) or "WhatsApp").strip()
                args["message_body"] = m.group(3).strip()
            else:
                target = blackboard.last_person or "Household_Contact"
                args["recipient"] = target
                args["app"] = "WhatsApp"
                args["message_body"] = resolved_task

        elif cap_id == "instagram.open_reels":
            target = "https://www.instagram.com/reels/"
            dur_m = re.search(r"(\d+)\s*(?:min|minute|minutes|sec|second|seconds)\b", lower)
            args["duration_val"] = int(dur_m.group(1)) if dur_m else 5
            args["url"] = target

        idem_seed = f"{cap_id}:{target}:{resolved_task.strip().lower()}"
        idempotency_key = f"idem_{hashlib.sha256(idem_seed.encode()).hexdigest()[:16]}"
        action_id = f"act_{int(time.time() * 1000)}_{idempotency_key[-6:]}"

        return Action(
            action_id=action_id,
            capability_id=cap_id,
            target=target,
            raw_instruction=resolved_task,
            validated_arguments=args,
            risk_class=risk_class,
            data_sensitivity=sensitivity,
            preconditions=preconds,
            postconditions=postconds,
            idempotency_key=idempotency_key,
            timeout_ms=cap_meta.timeout_ms if cap_meta else 15000,
        )


intent_compiler = TypedIntentCompiler()
