import os
from typing import Dict, Any, Optional

try:
    from agent.hardware.runtime_adapter import detect_hardware_tier, RuntimeTier
except ImportError:
    class RuntimeTier:
        LOW_SPEC_MOBILE = "low_spec_mobile"
        MID_SPEC = "mid_spec"
        HIGH_SPEC = "high_spec"

    def detect_hardware_tier():
        is_android = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ
        return RuntimeTier.LOW_SPEC_MOBILE if is_android else RuntimeTier.MID_SPEC


class LedgerPromptBuilder:
    def __init__(self, token_ceiling: int = 8192, warning_ratio: float = 0.75, critical_ratio: float = 0.88):
        self.tier = detect_hardware_tier()
        
        # Adaptive window budgets: Mobile usually runs with smaller KV caches (4k-8k)
        if self.tier == RuntimeTier.LOW_SPEC_MOBILE:
            self.token_ceiling = min(token_ceiling, 4096)
        else:
            self.token_ceiling = token_ceiling

        self.warning_limit = int(self.token_ceiling * warning_ratio)
        self.critical_limit = int(self.token_ceiling * critical_ratio)

    def calculate_meter(self, current_tokens: int) -> Dict[str, Any]:
        """Hardware-adaptive context meter calculation."""
        pct = min(100, int((current_tokens / self.token_ceiling) * 100))
        
        if current_tokens >= self.critical_limit:
            status = "CRITICAL_OVERFLOW_IMMINENT"
            action_instruction = "MANDATORY: You MUST invoke ledger_turn_the_page on this turn. Do NOT execute any other tool."
        elif current_tokens >= self.warning_limit:
            status = "WARNING_WINDOW_SATURATED"
            action_instruction = "RECOMMENDED: Prepare checkpoint. If your current micro-task has completed, invoke ledger_turn_the_page now."
        else:
            status = "HEALTHY"
            action_instruction = "Proceed with normal tool execution. Update milestones as tasks complete."

        return {
            "current_tokens": current_tokens,
            "ceiling": self.token_ceiling,
            "pct": pct,
            "status": status,
            "instruction": action_instruction
        }

    def build_system_prompt(self, role: str, base_instructions: str, current_tokens: int = 0) -> str:
        meter = self.calculate_meter(current_tokens)
        
        # Mobile/Termux template: Strips excessive whitespace and redundant words to save KV cache
        if self.tier == RuntimeTier.LOW_SPEC_MOBILE:
            return f"""[SYSTEM: {role.upper()}]
{base_instructions}

[CONTEXT METER: {meter['pct']}% ({meter['current_tokens']}/{meter['ceiling']} tokens) | STATUS: {meter['status']}]
RULE: {meter['instruction']}

TRIGGER RULES FOR `ledger_turn_the_page`:
1. If STATUS is CRITICAL_OVERFLOW_IMMINENT -> Call `ledger_turn_the_page` immediately.
2. If you just finished a subtask (e.g., ran a test or edited a file) AND status is WARNING -> Call `ledger_turn_the_page`.
3. Never summarize into text; always use the `ledger_turn_the_page` function call.
"""

        # Desktop / Server template: Complete Markdown scaffolding
        return f"""# SYSTEM IDENTITY & WORKFLOW: {role.upper()}
{base_instructions}

---
## REAL-TIME CONTEXT BUDGET MONITOR
- **Current Token Load**: {meter['current_tokens']} / {meter['ceiling']} tokens ({meter['pct']}%)
- **Buffer State**: `{meter['status']}`
- **Active Directive**: **{meter['instruction']}**

---
## AUTONOMOUS MEMORY PROTOCOL: `ledger_turn_the_page`
Local models suffer from context decay if history exceeds safety margins. You are strictly governed by these page-turn rules:

1. **Deterministic Eviction Threshold**: When Buffer State is `CRITICAL_OVERFLOW_IMMINENT` or `WARNING_WINDOW_SATURATED`, your priority shifts from code execution to state preservation.
2. **Phase Boundary Rule**: Whenever you finish writing a file or running a test suite, check the Context Meter. If above 70%, trigger `ledger_turn_the_page`.
3. **Turn-the-Page Payload Contract**:
   - `checkpoint_summary`: Must state exact files modified, functions changed, and test exit codes.
   - `immediate_next_step`: Must provide unambiguous instructions for Turn 0 of the next window (e.g., "Run pytest tests/test_parser.py and fix line 42").
   - `active_hypotheses`: Carry forward unproven assumptions so context isn't lost.
4. **Execution Prohibition**: When calling `ledger_turn_the_page`, do NOT append explanatory chatter or markdown prose. Return ONLY the tool execution payload.
"""
