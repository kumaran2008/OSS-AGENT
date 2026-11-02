from agent.prompts.ledger_prompts import LedgerPromptBuilder

builder = LedgerPromptBuilder(token_ceiling=4096)

# Case 1: Healthy Context (Turn 1)
print("=== CASE 1: HEALTHY CONTEXT ===")
prompt_turn_1 = builder.build_system_prompt(
    role="builder",
    base_instructions="Implement unit tests for session manager.",
    current_tokens=850
)
print(prompt_turn_1)

# Case 2: Saturated Context (Turn 7)
print("=== CASE 2: CONTEXT REACHING WARNING LIMIT ===")
prompt_turn_7 = builder.build_system_prompt(
    role="builder",
    base_instructions="Implement unit tests for session manager.",
    current_tokens=3200
)
print(prompt_turn_7)

# Case 3: Critical Context (Turn 10) - Forced Rollover
print("=== CASE 3: CRITICAL LIMIT (FORCED ROLLOVER) ===")
prompt_turn_10 = builder.build_system_prompt(
    role="builder",
    base_instructions="Implement unit tests for session manager.",
    current_tokens=3750
)
print(prompt_turn_10)
