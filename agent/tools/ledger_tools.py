from typing import Any, Dict, List, Tuple
from agent.memory.codex_store import PersistentCodexLedger, codex_ledger


# --- OpenAI / MCP Compatible Tool Schemas ---
LEDGER_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ledger_record_invariant",
            "description": "Record an architectural rule, hard constraint, or immutable decision that future turns must adhere to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invariant": {
                        "type": "string",
                        "description": "The technical constraint to enforce (e.g., 'Use async def for all route handlers').",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this constraint was established (e.g., 'Avoid event loop blocking in FastAPI').",
                    },
                },
                "required": ["invariant", "rationale"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ledger_record_failed_hypothesis",
            "description": "Record a discarded approach, broken patch, or failed debugging hypothesis so future turns will not repeat it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "failed_approach": {
                        "type": "string",
                        "description": "The exact solution or pattern that failed.",
                    },
                    "reason_or_error": {
                        "type": "string",
                        "description": "The compiler error, test failure, or unexpected regression that invalidated this approach.",
                    },
                },
                "required": ["failed_approach", "reason_or_error"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ledger_manage_milestones",
            "description": "Update task execution state by marking existing milestones completed or adding newly discovered sub-tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["complete", "add"],
                        "description": "Action to perform: 'complete' marks an existing milestone done, 'add' schedules a new pending milestone.",
                    },
                    "milestone": {
                        "type": "string",
                        "description": "The exact description of the milestone (e.g., 'Implement routes/health.py').",
                    },
                },
                "required": ["action", "milestone"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ledger_turn_the_page",
            "description": "Trigger an immediate context rollover. Persists a distilled checkpoint and wipes conversational history back to Turn 0.",
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_summary": {
                        "type": "string",
                        "description": "High-density technical distillation of what was accomplished and current state.",
                    },
                    "immediate_next_step": {
                        "type": "string",
                        "description": "The exact first action Turn 0 of the new context window must take.",
                    },
                    "active_hypotheses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Unverified assumptions or pending questions to carry across the rollover.",
                    },
                },
                "required": ["checkpoint_summary", "immediate_next_step", "active_hypotheses"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]


class LedgerToolDispatcher:
    """Runtime dispatcher connecting model function calls directly to PersistentCodexLedger."""

    def __init__(self, ledger: PersistentCodexLedger = codex_ledger):
        self.ledger = ledger

    def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        """
        Executes ledger operations.
        Returns:
            Tuple[str, bool]: (result_message_for_llm, trigger_context_flush_flag)
        """
        if tool_name == "ledger_record_invariant":
            inv = arguments.get("invariant", "").strip()
            rationale = arguments.get("rationale", "").strip()
            if not inv:
                return "Error: 'invariant' cannot be empty.", False

            rule = f"{inv} (Rationale: {rationale})" if rationale else inv
            self.ledger.record_decision(rule)
            return f"Invariant recorded: '{inv}'", False

        elif tool_name == "ledger_record_failed_hypothesis":
            approach = arguments.get("failed_approach", "").strip()
            reason = arguments.get("reason_or_error", "").strip()
            if not approach:
                return "Error: 'failed_approach' cannot be empty.", False

            failure_entry = f"{approach} — Error/Reason: {reason}" if reason else approach
            self.ledger.record_failed_hypothesis(failure_entry)
            return f"Discarded approach recorded: '{approach}'", False

        elif tool_name == "ledger_manage_milestones":
            action = arguments.get("action")
            milestone = arguments.get("milestone", "").strip()
            if not milestone:
                return "Error: 'milestone' cannot be empty.", False

            if action == "complete":
                self.ledger.complete_milestone(milestone)
                return f"Milestone marked complete: '{milestone}'", False
            elif action == "add":
                self.ledger.add_pending_milestone(milestone)
                return f"New pending milestone registered: '{milestone}'", False
            return f"Invalid action: '{action}'. Must be 'complete' or 'add'.", False

        elif tool_name == "ledger_turn_the_page":
            checkpoint = arguments.get("checkpoint_summary", "Session checkpoint reached.")
            next_step = arguments.get("immediate_next_step", "Continue task execution.")
            hypotheses = arguments.get("active_hypotheses", [])

            # 1. Carry over active hypotheses safely into ledger state
            for h in hypotheses:
                h_str = str(h).strip()
                if h_str and h_str not in self.ledger.state.unconfirmed_hypotheses:
                    self.ledger.state.unconfirmed_hypotheses.append(h_str)

            # 2. Archive checkpoint out-of-band to prevent history bloat
            self.ledger.archive_turn(
                tool_name="PAGE_TURN_CHECKPOINT",
                payload=checkpoint,
                result=f"Next Step: {next_step}",
            )

            # 3. Increment window counter and synthesize fresh Turn 0 context
            rehydration_prompt = self.ledger.turn_the_page()

            # Returning True commands the agent loop to clear message arrays
            return rehydration_prompt, True

        return f"Unknown tool: '{tool_name}'", False
