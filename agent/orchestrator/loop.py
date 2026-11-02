import os
import sys
import json
import time
from typing import Dict, Any, List, Optional, Tuple

from agent.memory.federated_ledger import SharedRootLedger, WorkerAgentScratchpad
from agent.memory.turn_retriever import FederatedTurnRetriever
from agent.prompts.ledger_prompts import LedgerPromptBuilder


def estimate_tokens(text_or_messages: Any) -> int:
    if isinstance(text_or_messages, str):
        return max(1, len(text_or_messages) // 4)
    elif isinstance(text_or_messages, list):
        total_chars = 0
        for msg in text_or_messages:
            if isinstance(msg, dict):
                total_chars += len(msg.get("content", ""))
            else:
                total_chars += len(str(msg))
        return max(1, total_chars // 4)
    return 1


class LedgerToolDispatcher:
    def __init__(self, workspace_root: str, root_ledger: SharedRootLedger, worker: WorkerAgentScratchpad):
        self.workspace_root = workspace_root
        self.root = root_ledger
        self.worker = worker
        self.retriever = FederatedTurnRetriever(workspace_root)

    def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        if tool_name == "ledger_record_invariant":
            inv = arguments.get("invariant", "")
            rationale = arguments.get("rationale", "")
            formatted = f"{inv} (Rationale: {rationale})" if rationale else inv
            self.worker.propose_invariant(formatted)
            return f"Invariant staged: {inv}", False

        elif tool_name == "ledger_manage_milestones":
            action = arguments.get("action")
            milestone = arguments.get("milestone", "")
            if action == "complete":
                self.worker.complete_subtask(milestone)
                return f"Milestone marked complete: {milestone}", False
            elif action == "add":
                if milestone not in self.worker.data.pending_milestones:
                    self.worker.data.pending_milestones.append(milestone)
                return f"Milestone queued: {milestone}", False
            return "Unknown milestone action", False

        elif tool_name == "ledger_query_memory":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", 4)
            hits = self.retriever.search(query=query, task_slug=self.root.task_slug, top_k=top_k)
            
            if not hits:
                return f"No memory matches found for query: '{query}'", False

            formatted_hits = []
            for h in hits:
                formatted_hits.append(
                    f"[{h.source_type} | {h.source_id} > {h.section}] (Score: {h.relevance_score})\n"
                    f"  {h.content}"
                )
            return "\n\n".join(formatted_hits), False

        elif tool_name == "ledger_turn_the_page":
            summary = arguments.get("checkpoint_summary", "Window cycle complete.")
            next_step = arguments.get("immediate_next_step", "Resume pending milestone.")
            hypotheses = arguments.get("active_hypotheses", [])
            
            self.worker.sync_to_root(verified_facts=[f"Checkpoint: {summary}"])
            
            for h in hypotheses:
                self.worker.record_hypothesis(h)

            rehydration_prompt = (
                f"[CONTEXT RESTORATION - NEW WINDOW]\n"
                f"PREVIOUS WINDOW SUMMARY: {summary}\n"
                f"IMMEDIATE DIRECTIVE: {next_step}\n\n"
                f"{self.worker.build_context_prompt()}"
            )
            return rehydration_prompt, True

        return f"Unknown tool: {tool_name}", False


class AutonomousAgentLoop:
    def __init__(
        self,
        workspace_root: str,
        task_slug: str,
        agent_id: str,
        role: str,
        base_instructions: str,
        token_ceiling: int = 4096
    ):
        self.workspace_root = workspace_root
        self.task_slug = task_slug
        self.role = role
        self.base_instructions = base_instructions
        
        self.root_ledger = SharedRootLedger(workspace_root, task_slug)
        self.worker = WorkerAgentScratchpad(self.root_ledger, agent_id, role)
        self.prompt_builder = LedgerPromptBuilder(token_ceiling=token_ceiling)
        self.dispatcher = LedgerToolDispatcher(workspace_root, self.root_ledger, self.worker)
        
        self.messages: List[Dict[str, str]] = []
        self.window_index = 1

    def count_active_tokens(self) -> int:
        return estimate_tokens(self.messages)

    def reset_context(self, rehydration_prompt: str):
        self.window_index += 1
        self.messages.clear()
        self.messages.append({"role": "user", "content": rehydration_prompt})

    def run_turn(self, simulated_llm_response: Dict[str, Any]) -> str:
        current_tokens = self.count_active_tokens()
        active_system_prompt = self.prompt_builder.build_system_prompt(
            role=self.role,
            base_instructions=self.base_instructions,
            current_tokens=current_tokens
        )

        tool_call = simulated_llm_response.get("tool_call")
        if tool_call:
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})
            
            tool_output, should_flush = self.dispatcher.dispatch(tool_name, tool_args)
            
            if should_flush:
                print(f"\n[LOOP] >>> Context rollover triggered! Resetting to Window {self.window_index + 1}...")
                self.reset_context(rehydration_prompt=tool_output)
                return f"[PAGE_TURNED] Reseeded Window {self.window_index}"
            else:
                self.messages.append({"role": "assistant", "content": f"Ran tool {tool_name}"})
                self.messages.append({"role": "tool", "content": tool_output})
                return f"[TOOL_EXECUTED] {tool_output}"

        content = simulated_llm_response.get("content", "")
        self.messages.append({"role": "assistant", "content": content})
        return f"[MESSAGE] {content}"
