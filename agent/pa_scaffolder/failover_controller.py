import asyncio
from typing import AsyncGenerator, Dict, Any, Optional, Tuple

from agent.pa_scaffolder.wallet import OSSWallet
from agent.pa_scaffolder.smart_llm_gateway import SmartLLMGateway
from agent.pa_scaffolder.local_slm_engine import LocalSLMEngine
from agent.pa_scaffolder.cdp_bridge import ResilientCDPBridge


class MultiModelFailoverController:
    """
    Live Multi-Model Routing & Resilient Failover Controller.
    Cascades gracefully across compute tiers without dropping user conversational turns.
    """

    def __init__(
        self,
        wallet: Optional[OSSWallet] = None,
        llm_gateway: Optional[SmartLLMGateway] = None,
        local_slm: Optional[LocalSLMEngine] = None,
        cdp_bridge: Optional[ResilientCDPBridge] = None
    ):
        self.wallet = wallet or OSSWallet()
        self.llm_gateway = llm_gateway or SmartLLMGateway(wallet=self.wallet)
        self.local_slm = local_slm or LocalSLMEngine()
        self.cdp_bridge = cdp_bridge or ResilientCDPBridge()

    async def execute_resilient_stream(
        self,
        prompt: str,
        initial_tier: int = 2,
        force_failover_429: bool = False
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """
        Streams (token_chunk, active_engine_label).
        If initial_tier fails (e.g. 429 rate limit or empty balance), cascades to next tier.
        """
        # -------------------------------------------------------------
        # ATTEMPT 1: TIER 2 (DeepSeek Flash)
        # -------------------------------------------------------------
        if initial_tier == 2:
            can_use_paid = self.wallet.has_funds() and not force_failover_429
            if can_use_paid:
                try:
                    yield ("[Tier 2: DeepSeek Flash] ", "TIER_2_FRONTIER")
                    async for token in self.llm_gateway.stream_tokens(prompt):
                        yield (token, "TIER_2_FRONTIER")
                    return
                except Exception as e:
                    # Emulate/catch HTTP 429 or network drop
                    pass

            # Failover Triggered!
            yield ("\n[Failover: Tier 2 unavailable -> Falling over to Tier 3 Desktop CDP]\n", "FAILOVER_EVENT")

        # -------------------------------------------------------------
        # ATTEMPT 2: TIER 3 (Desktop Browser CDP Bridge)
        # -------------------------------------------------------------
        if initial_tier in [2, 3]:
            try:
                yield ("[Tier 3: Desktop CDP] ", "TIER_3_CDP")
                async for token in self.cdp_bridge.stream_browser_generation(prompt, timeout=8.0):
                    yield (token, "TIER_3_CDP")
                return
            except Exception:
                yield ("\n[Failover: Desktop Chrome offline -> Falling over to Tier 1 Local SLM]\n", "FAILOVER_EVENT")

        # -------------------------------------------------------------
        # ATTEMPT 3: TIER 1 (Offline Edge SLM / In-Memory Reasoning Advisor)
        # -------------------------------------------------------------
        yield ("[Tier 1: Local SLM] ", "TIER_1_EDGE_SLM")
        async for token in self.local_slm.stream_tokens(prompt):
            yield (token, "TIER_1_EDGE_SLM")
