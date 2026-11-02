import asyncio
from pathlib import Path

from agent.pa_scaffolder.wallet import OSSWallet
from agent.pa_scaffolder.jev_reflex_router import JevDecisionEngine
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


def set_wallet_balance(wallet: OSSWallet, amount: float):
    if hasattr(wallet, "_balance"):
        wallet._balance = float(amount)
    else:
        wallet.balance = float(amount)


async def test_jev_cdp_screen_triage():
    print("=" * 70)
    print("     JEV ZERO-BALANCE CDP FALLBACK & SCREEN TRIAGE AUDIT")
    print("=" * 70)

    harness = UnifiedAsyncEngine()

    # -------------------------------------------------------------------------
    # 1. Verify Jev Wallet-Zero Fallback to Desktop CDP
    # -------------------------------------------------------------------------
    print("\n[1/3] Testing Jev Routing When Wallet Has 0 Balance...")
    # Drain wallet
    set_wallet_balance(harness.wallet, 0.00)
    assert not harness.wallet.has_funds()

    decision = await harness.jev.evaluate_async(
        utterance="explain the architecture of transformer attention",
        wallet_has_funds=harness.wallet.has_funds()
    )
    print(f" • Wallet Balance:       ${harness.wallet.balance:.2f}")
    print(f" • Jev Routing Decision: Tier={decision['urgency_tier']} | Backend={decision['execution_backend']}")
    assert decision["urgency_tier"] == "FREE_DESKTOP_CDP"
    assert decision["execution_backend"] == "DESKTOP_CDP_BROWSER"
    print(" >>> CRITERION 1 PASSED: Zero-balance automatically routed to free Desktop CDP. <<<")

    # -------------------------------------------------------------------------
    # 2. Verify Visual Screen Code Triage (Screenshot + Clipboard Split)
    # -------------------------------------------------------------------------
    print("\n[2/3] Testing Screen Code Triage ('I am stuck on this error')...")
    # Reset wallet balance to active
    set_wallet_balance(harness.wallet, 1.00)

    print(f" • Active Frontier Model Configured: '{harness.claude.model}'")

    triage_turn = await harness.process_voice_turn("I am stuck on this error on my screen, fix it")
    print(f" • Intent Detected:      {triage_turn['intent']}")
    print(f" • Backend Executed:     {triage_turn['execution_backend']}")
    print(f" • Screenshot Attached:  {triage_turn['image_attached']}")
    print(f" • Clipboard Written:    {triage_turn['clipboard_copied']}")
    print(f" • Spoken Reason Only:   \"{triage_turn['spoken_response']}\"")

    assert triage_turn["intent"] == "SCREEN_CODE_TRIAGE"
    assert triage_turn["clipboard_copied"] is True

    # Check clipboard content directly
    clip_text = harness.tools.desktop.get_clipboard()
    print(f"\n • Actual Clipboard Content:\n---\n{clip_text}\n---")
    assert "def solve_boundary" in clip_text
    assert "<clipboard_code>" not in clip_text
    assert "<spoken_reason>" not in clip_text
    assert "You had an out-of-bounds" not in clip_text
    print(" >>> CRITERION 2 PASSED: Code copied cleanly to clipboard; reason spoken aloud. <<<")

    # -------------------------------------------------------------------------
    # 3. Verify Jev-Driven Local Mode Switch (Sub-Millisecond)
    # -------------------------------------------------------------------------
    print("\n[3/3] Testing Jev Fast Mode Evaluator...")
    ok, mode_name, msg = harness.jev.evaluate_mode("enter builder mode", current_mode="normal")
    print(f" • Mode Match:           {ok} -> {mode_name}")
    print(f" • Jev Evaluation Msg:   \"{msg}\"")
    assert ok is True
    assert mode_name == "builder"
    print(" >>> CRITERION 3 PASSED: Jev evaluates mode switches locally. <<<")

    harness.tools.close()

    print("\n" + "=" * 70)
    print(">>> JEV CDP FALLBACK, SCREEN TRIAGE & CLIPBOARD SYSTEM OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_jev_cdp_screen_triage())
