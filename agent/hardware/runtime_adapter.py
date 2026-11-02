import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    # Ingest existing environment/hardware detection module
    from llm.hardware_engine import get_hardware_profile
except ImportError:
    try:
        from agent.hardware_engine import get_hardware_profile
    except ImportError:
        def get_hardware_profile() -> Dict[str, Any]:
            is_termux = os.path.exists("/data/data/com.termux")
            return {
                "tier": "low" if is_termux else "high",
                "is_mobile": is_termux,
                "ram_gb": 4 if is_termux else 16,
                "has_gpu": False if is_termux else True,
                "has_ollama": False if is_termux else True,
            }


@dataclass
class AdaptiveRuntimeConfig:
    tier: str  # "low" | "mid" | "high"
    is_mobile: bool
    memory_strategy: str      # "sqlite_fts5_bm25" (low) vs "hybrid_dense_vector" (high)
    verification_strategy: str  # "pure_ast" (low) vs "full_typecheck_lsp" (high)
    debate_strategy: str        # "single_pass_self_critique" (low) vs "multi_agent_consensus" (high)
    inference_provider: str     # "openrouter" (low) vs "ollama" (high)


class HardwareRuntimeAdapter:
    """Translates hardware audit outputs into operational execution strategies."""

    def __init__(self):
        self.profile = get_hardware_profile()
        self.config = self._resolve_config(self.profile)

    def _resolve_config(self, profile: Dict[str, Any]) -> AdaptiveRuntimeConfig:
        tier = profile.get("tier", "low").lower()
        is_mobile = profile.get("is_mobile", False) or os.path.exists("/data/data/com.termux")

        if is_mobile or tier == "low":
            return AdaptiveRuntimeConfig(
                tier="low",
                is_mobile=True,
                memory_strategy="sqlite_fts5_bm25",
                verification_strategy="pure_ast",
                debate_strategy="single_pass_self_critique",
                inference_provider="openrouter",
            )
        elif tier == "mid":
            return AdaptiveRuntimeConfig(
                tier="mid",
                is_mobile=False,
                memory_strategy="sqlite_fts5_bm25",
                verification_strategy="pure_ast_with_linter",
                debate_strategy="multi_agent_consensus",
                inference_provider="hybrid",
            )
        else:
            return AdaptiveRuntimeConfig(
                tier="high",
                is_mobile=False,
                memory_strategy="hybrid_dense_vector",
                verification_strategy="full_typecheck_lsp",
                debate_strategy="multi_agent_consensus",
                inference_provider="ollama",
            )

    def route_debate(self, prompt: str, mason_output: str, reviewer_callback: Any, mason_callback: Any) -> str:
        """
        Executes adversarial validation adaptively:
        - Low Spec / Mobile: Single-pass self-critique (saves 50% tokens and latency).
        - High Spec: Full multi-agent turn-based debate.
        """
        if self.config.debate_strategy == "single_pass_self_critique":
            # Mobile path: Have the Mason critique and patch its own draft in one follow-up
            critique_prompt = (
                f"Perform a strict review of your code for syntax, imports, and security boundaries:\n"
                f"{mason_output}\n"
                f"Emit only the final corrected code wrapped in standard markdown fences."
            )
            return mason_callback(critique_prompt)
        else:
            # High-spec path: Mason vs Reviewer dynamic consensus
            critique = reviewer_callback(mason_output)
            repair_prompt = f"Address this reviewer critique and fix the patch:\n{critique}\nOriginal:\n{mason_output}"
            return mason_callback(repair_prompt)


# Global adapter instance
runtime_adapter = HardwareRuntimeAdapter()
