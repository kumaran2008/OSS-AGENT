from __future__ import annotations

import importlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.plugin_host import plugin_host


@dataclass
class RegisteredCapabilityEntry:
    capability: str
    plugin: str
    description: str
    available: bool
    requires_auth: bool
    risk_level: str                # "low" | "medium" | "high" | "critical"
    requires_approval: bool
    verification_method: str
    execution_substrate: str       # "PYTHON_DETERMINISTIC" | "INDEXED_RETRIEVAL" | "MCP_STDIO" | "PLUGIN_RUNTIME" | "SUITE_WORKFLOW"
    fallback_capability: Optional[str] = None
    source_module: str = ""
    last_verified_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "plugin": self.plugin,
            "description": self.description,
            "available": self.available,
            "requires_auth": self.requires_auth,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "verification_method": self.verification_method,
            "execution_substrate": self.execution_substrate,
            "fallback_capability": self.fallback_capability,
            "source_module": self.source_module,
            "last_verified_at": self.last_verified_at,
        }


class UniversalCapabilityRegistry:
    """Section 14: Live Universal Capability Registry (`agent/kernel/capability_registry.py`).
    Maintains a single authoritative truth table of everything Friday can do across:
      1. Hot-mounted `AppPlugin` instances in `plugin_host`.
      2. Verified MCP servers & learned tools in `mcp_bridge_plugin`.
      3. Specialized `agent/pa_scaffolder/` engines (RepoSymbolMapper, LiteratureEngine,
         AdvancedOBSClient, DesktopCDPEngine, OSNavigator, MathAndStatsVerifier).
      4. Deterministic Python kernel operations (sorting, math, file hashing, mode switches).
    """

    DB_PATH = Path("workspace/kernel_governance.db")

    RISK_MAP = {
        "read": ("low", False),
        "transform": ("low", False),
        "local_write": ("medium", False),
        "external_write": ("high", True),
        "destructive": ("critical", True),
        "sensitive": ("critical", True),
    }

    PA_SCAFFOLDER_BRIDGES = [
        ("github.create_pull_request", "plugins.github_plugin", "GitHubBridge", "Creates verified pull requests and inspects repository issues via GitHub API.", "high", True, "github_api_check", "PLUGIN_RUNTIME"),
        ("whatsapp.send_verified_message", "plugins.whatsapp_plugin", "MessagingSchedulePlugin", "Sends user-approved WhatsApp messages with idempotency protection.", "high", True, "outbox_receipt_check", "PLUGIN_RUNTIME"),
        ("discord.read_channel_summary", "plugins.discord_plugin", "MessagingSchedulePlugin", "Retrieves and summarizes authorized Discord channel discussions.", "low", False, "discord_api_check", "PLUGIN_RUNTIME"),
        ("slack.post_team_update", "plugins.slack_plugin", "MessagingSchedulePlugin", "Posts verified updates to authorized Slack channels.", "high", True, "slack_api_check", "PLUGIN_RUNTIME"),
        ("arxiv.fetch_papers", "plugins.arxiv_plugin", "LiteratureEngine", "Queries arXiv preprints and extracts equations and methodology sections.", "low", False, "arxiv_metadata_check", "SUITE_WORKFLOW"),
        ("pubmed.search_biomedical", "plugins.pubmed_plugin", "LiteratureEngine", "Searches PubMed biomedical literature and clinical study metadata.", "low", False, "pubmed_pmid_check", "SUITE_WORKFLOW"),
        ("calendar.schedule_event", "plugins.calendar_plugin", "MessagingSchedulePlugin", "Schedules timezone-aware calendar events and conditional task reminders.", "medium", False, "calendar_slot_check", "PLUGIN_RUNTIME"),
        ("filesystem.quarantine_verify", "plugins.filesystem_plugin", "UniversalReader", "Verifies downloaded files in quarantine via magic-byte and taint checks.", "low", False, "sha256_magic_byte_check", "PYTHON_DETERMINISTIC"),
        ("terminal.sandboxed_exec", "plugins.terminal_plugin", "IsolatedSubprocessSandbox", "Executes terminal commands inside the sys.addaudithook child-process jail.", "medium", False, "exit_code_audit_check", "PLUGIN_RUNTIME"),
        ("audio.dual_channel_route", "plugins.audio_plugin", "AdvancedStreamCompanion", "Routes audio strictly between OBS public mix and private headphone IEM channel.", "low", False, "audio_route_isolation_check", "PYTHON_DETERMINISTIC"),
        ("repo.symbol_index", "pa_scaffolder.repo_symbol_mapper", "RepoSymbolMapper", "Indexes repository AST symbols, imports, and call graphs across languages.", "low", False, "ast_symbol_count_check", "INDEXED_RETRIEVAL"),
        ("code.ast_patch", "pa_scaffolder.code_patcher", "ASTCodePatcher", "Applies syntax-verified AST transformations and incremental diffs.", "medium", False, "shadow_twin_7point_check", "PLUGIN_RUNTIME"),
        ("research.literature_search", "pa_scaffolder.literature_engine", "LiteratureEngine", "Searches academic papers (arXiv, Semantic Scholar, PubMed) and ranks citation impact.", "low", False, "citation_metadata_check", "SUITE_WORKFLOW"),
        ("research.claim_matrix", "pa_scaffolder.research_memory", "ResearchMemoryLayer", "Stores paper claims, experimental results, dead-ends, and detects contradictions.", "low", False, "sqlite_claim_row_check", "INDEXED_RETRIEVAL"),
        ("research.math_stats_verify", "pa_scaffolder.math_verifier", "MathAndStatsVerifier", "Runs deterministic statistical and mathematical equation verification in Python.", "low", False, "scipy_numpy_audit_check", "PYTHON_DETERMINISTIC"),
        ("stream.obs_broadcast_control", "pa_scaffolder.advanced_companion", "AdvancedStreamCompanion", "Controls OBS scenes, dual-channel audio routing, and stream companion state.", "medium", False, "obs_state_receipt_check", "SUITE_WORKFLOW"),
        ("voice.wakeword_vad_gate", "pa_scaffolder.vad_wakeword_engine", "WakeWordGatingFilter", "Enforces persona wake-word gating and voice activity detection during gaming/streaming.", "low", False, "vad_frame_gate_check", "PYTHON_DETERMINISTIC"),
        ("browser.cdp_dom_automation", "pa_scaffolder.desktop_cdp_engine", "DesktopCDPEngine", "Automates browser tabs and extracts live DOM accessibility trees via Chrome DevTools Protocol.", "medium", False, "dom_selector_postcondition_check", "PLUGIN_RUNTIME"),
        ("desktop.os_accessibility_nav", "pa_scaffolder.os_navigator", "OSNavigator", "Navigates native OS windows and UI accessibility elements.", "medium", False, "window_process_check", "PLUGIN_RUNTIME"),
        ("health.nutrition_vision_estimate", "pa_scaffolder.vision_engine", "MultimodalVisionEngine", "Estimates meal calories and macro ranges with confidence intervals from food images.", "low", False, "nutrition_range_schema_check", "SUITE_WORKFLOW"),
    ]

    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, RegisteredCapabilityEntry] = {}
        self._init_db()
        self.refresh_registry()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS universal_capability_registry (
                    capability TEXT PRIMARY KEY,
                    plugin TEXT NOT NULL,
                    description TEXT NOT NULL,
                    available INTEGER NOT NULL,
                    requires_auth INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL,
                    verification_method TEXT NOT NULL,
                    execution_substrate TEXT NOT NULL,
                    fallback_capability TEXT,
                    source_module TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def refresh_registry(self) -> Dict[str, Any]:
        """Dynamically introspects all plugins, MCP tools, and pa_scaffolder modules."""
        now = time.time()
        # 1. Register deterministic Python kernel capabilities
        deterministic_caps = [
            RegisteredCapabilityEntry(
                capability="python.deterministic_compute",
                plugin="kernel.python",
                description="Performs exact mathematical calculations, percentage math, sorting, and file hashing in Python without LLM calls.",
                available=True,
                requires_auth=False,
                risk_level="low",
                requires_approval=False,
                verification_method="deterministic_return_check",
                execution_substrate="PYTHON_DETERMINISTIC",
                source_module="agent.kernel.native",
                last_verified_at=now,
            ),
            RegisteredCapabilityEntry(
                capability="model.switch_voice",
                plugin="kernel.model_broker",
                description="Switches active generative AI model by voice command or resets to default DeepSeek V4.1 Flash.",
                available=True,
                requires_auth=False,
                risk_level="low",
                requires_approval=False,
                verification_method="sqlite_model_override_check",
                execution_substrate="PYTHON_DETERMINISTIC",
                source_module="agent.kernel.model_broker",
                last_verified_at=now,
            ),
        ]
        for dc in deterministic_caps:
            self._entries[dc.capability] = dc

        # 2. Introspect all capabilities registered in `plugin_host`
        all_plugin_caps = getattr(plugin_host, "_capabilities", {}) or getattr(plugin_host, "capabilities", {})
        if not all_plugin_caps and hasattr(plugin_host, "discover_all"):
            plugin_host.discover_all()
            all_plugin_caps = getattr(plugin_host, "_capabilities", {}) or getattr(plugin_host, "capabilities", {})
        for cap_id, cap_obj in all_plugin_caps.items():
            r_lvl, req_app = self.RISK_MAP.get(cap_obj.risk_class, ("medium", False))
            is_enabled = cap_obj.plugin_id not in plugin_host._disabled_plugins
            substrate = "MCP_STDIO" if cap_id.startswith("mcp.") else "PLUGIN_RUNTIME"
            fallback = "vision.screen_analyze" if cap_id == "instagram.open_reels" else None
            self._entries[cap_id] = RegisteredCapabilityEntry(
                capability=cap_id,
                plugin=cap_obj.plugin_id,
                description=cap_obj.description,
                available=is_enabled,
                requires_auth=(cap_obj.execution_backend == "OFFICIAL_API"),
                risk_level=r_lvl,
                requires_approval=req_app,
                verification_method="postcondition_receipt_verifier",
                execution_substrate=substrate,
                fallback_capability=fallback,
                source_module=f"agent.plugins.{cap_obj.plugin_id.replace('plugin.', '')}_plugin",
                last_verified_at=now,
            )

        # 3. Dynamically probe `agent/pa_scaffolder/` modules on disk
        for cap_id, mod_name, cls_name, desc, r_lvl, req_app, ver_method, substrate in self.PA_SCAFFOLDER_BRIDGES:
            mod_file = Path("agent") / f"{mod_name.replace('.', '/')}.py"
            is_avail = mod_file.exists()
            self._entries[cap_id] = RegisteredCapabilityEntry(
                capability=cap_id,
                plugin=f"suite_engine.{mod_name.split('.')[-1]}",
                description=desc,
                available=is_avail,
                requires_auth=False,
                risk_level=r_lvl,
                requires_approval=req_app,
                verification_method=ver_method,
                execution_substrate=substrate,
                fallback_capability="builder.ast_inspect" if cap_id == "repo.symbol_index" else None,
                source_module=f"agent.{mod_name}",
                last_verified_at=now if is_avail else 0.0,
            )

        # Persist to SQLite
        with sqlite3.connect(self.DB_PATH) as conn:
            for entry in self._entries.values():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO universal_capability_registry (
                        capability, plugin, description, available, requires_auth,
                        risk_level, requires_approval, verification_method,
                        execution_substrate, fallback_capability, source_module, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.capability, entry.plugin, entry.description,
                        1 if entry.available else 0, 1 if entry.requires_auth else 0,
                        entry.risk_level, 1 if entry.requires_approval else 0,
                        entry.verification_method, entry.execution_substrate,
                        entry.fallback_capability, entry.source_module, now,
                    ),
                )
            conn.commit()

        return {
            "total_registered_capabilities": len(self._entries),
            "available_capabilities": sum(1 for e in self._entries.values() if e.available),
        }

    def get_capability_entry(self, capability_id: str) -> Optional[RegisteredCapabilityEntry]:
        return self._entries.get(capability_id)

    def list_capabilities(self, only_available: bool = True) -> List[Dict[str, Any]]:
        return [
            e.to_dict()
            for e in self._entries.values()
            if (not only_available or e.available)
        ]

    def select_capabilities_via_jev(self, task_objective: str, top_k: int = 3) -> Dict[str, Any]:
        """Uses TypeSafe AI `Jev` (`choice` + semantic alignment) over the live registry
        to select the best capability and execution substrate without hardcoded intent dictionaries!
        """
        avail_entries = [e for e in self._entries.values() if e.available]
        options = [e.capability for e in avail_entries[:250]]
        opt_descs = {e.capability: f"{e.capability} {e.description} {e.plugin}" for e in avail_entries[:250]}

        q_cap = {
            "best_capability": {
                "type": "choice",
                "options": options + ["other"],
                "default_option": options[0] if options else "other",
                "option_descriptions": opt_descs,
            }
        }
        prims = jev_ai_brain.evaluate_primitives(task_objective, q_cap)
        best_cap = prims["best_capability"].value
        probs = prims["best_capability"].probabilities
        ranked = sorted(
            [(cid, probs.get(cid, 0.0)) for cid in options],
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        entry = self._entries.get(best_cap)
        return {
            "selected_capability": best_cap,
            "confidence": prims["best_capability"].confidence,
            "execution_substrate": entry.execution_substrate if entry else "PLUGIN_RUNTIME",
            "requires_approval": entry.requires_approval if entry else False,
            "verification_method": entry.verification_method if entry else "postcondition_receipt_verifier",
            "fallback_capability": entry.fallback_capability if entry else None,
            "top_candidates": [{"capability": c, "probability": p} for c, p in ranked],
        }


capability_registry = UniversalCapabilityRegistry()
