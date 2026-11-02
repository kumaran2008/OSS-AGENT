import asyncio
from typing import Any
from agent.memory.codex_store import PersistentCodexLedger, codex_ledger


async def agent_orchestration_step(
    agent: Any,
    user_query: str,
    ledger: PersistentCodexLedger = codex_ledger,
    run_tool_fn: Any = None,
    token_reset_threshold: int = 40_000,
):
    """
    Autonomous ReAct execution harness governed by persistent Codex state
    and active context-window page turns.
    """
    # Turn 0: Initialize Task & Core Milestones
    ledger.update_objective(user_query)
    ledger.add_pending_milestone("Audit codebase for target bug")
    ledger.add_pending_milestone("Implement patch in isolation")
    ledger.add_pending_milestone("Run pytest suite to verify fix")

    # Ingest ledger state into agent instructions
    agent.system_prompt = f"System Rules...\n\n{ledger.render_rehydration_prompt()}"

    active_tokens = 0

    while getattr(ledger.state, "status", "IN_PROGRESS") == "IN_PROGRESS":
        # 1. Predict next step via cognitive model
        action = await agent.predict_next_step()

        # 2. Intercept and execute tools
        if getattr(action, "type", None) == "TOOL_EXECUTE":
            tool_name = getattr(action, "name", "")
            tool_args = getattr(action, "args", {})

            tool_output = ""
            if run_tool_fn:
                tool_output = await run_tool_fn(tool_name, tool_args)

            # Archive execution payload and result to disk
            ledger.archive_turn(tool_name, str(tool_args), str(tool_output))

            # Track affected files
            if tool_name in ["write_file", "apply_patch"] and "filepath" in tool_args:
                ledger.mark_file_modified(tool_args["filepath"])

        # 3. Check for context rollover boundary
        consumed = getattr(action, "consumed_tokens", 0)
        active_tokens += consumed

        if active_tokens > token_reset_threshold:
            print("[Harness] Approaching context boundary. Executing Page-Turn...")

            rehydration_context = ledger.turn_the_page()

            if hasattr(agent, "reset_context_window"):
                agent.reset_context_window()

            agent.system_prompt = rehydration_context
            active_tokens = 0
            break
