from pathlib import Path
from agent.pa_scaffolder.hybrid_voice import (
    HybridVoiceController,
    PrepaidWalletManager,
    VoiceEngineType
)
from agent.pa_scaffolder.advanced_companion import AudioRoute

print("=" * 65)
print("     SESSION SPEND LIMIT & AUTO-DROP VERIFICATION")
print("=" * 65)

# Setup wallet with $5.00
wallet = PrepaidWalletManager(wallet_path=Path("workspace/test_wallet_limit.json"))
wallet.data["balance_usd"] = 5.00
wallet._save()

# Initialize controller with a $0.01 limit (5 turns @ $0.002 each) to test quickly
controller = HybridVoiceController(wallet=wallet, session_spend_limit=0.01)

print("\n[1/4] Switching to Google Live with $0.01 Session Limit...")
switched, msg, _ = controller.process_voice_switch_command("use google live api to speak")
print(f" • Switch Result: {msg}")
assert switched is True
assert controller.active_engine == VoiceEngineType.GOOGLE_LIVE

print("\n[2/4] Simulating Spoken Turns within Budget...")
for i in range(1, 5):
    res = controller.synthesize_and_dispatch(f"Turn {i} audio banter", AudioRoute.EAR_ONLY)
    print(f" • Turn {i}: Engine={res['engine_used']} | Session Spent=${res['session_spent_usd']:.4f}")
    assert res["engine_used"] == "google_live"

print("\n[3/4] Triggering Turn That Hits the Session Limit ($0.0100)...")
res_cap = controller.synthesize_and_dispatch("Turn 5 audio banter", AudioRoute.EAR_ONLY)
print(f" • Turn 5: Engine={res_cap['engine_used']} | Spent=${res_cap['session_spent_usd']:.4f}")
print(f" • Auto-dropped flag: {res_cap.get('auto_dropped_to_kokoro')}")
assert res_cap["auto_dropped_to_kokoro"] is True
assert controller.active_engine == VoiceEngineType.KOKORO_LOCAL

print("\n[4/4] Verifying Subsequent Turns Run on Kokoro at $0.00...")
res_subsequent = controller.synthesize_and_dispatch("Turn 6 question", AudioRoute.EAR_ONLY)
print(f" • Turn 6: Engine={res_subsequent['engine_used']} | Cost=${res_subsequent['cost_deducted']:.2f}")
if "notice" in res_subsequent:
    print(f" • Notice: {res_subsequent['notice']}")
assert res_subsequent["engine_used"] == "kokoro_local"
assert res_subsequent["cost_deducted"] == 0.00

# Verify switch command is blocked
switched_again, block_msg, _ = controller.process_voice_switch_command("use google live api")
print(f" • Re-switch attempt blocked: \"{block_msg}\"")
assert switched_again is False

# Reset session spend and verify switch works again
controller.reset_session_spend()
switched_reset, reset_msg, _ = controller.process_voice_switch_command("use google live api")
print(f" • After reset: Switched={switched_reset} | \"{reset_msg}\"")
assert switched_reset is True
assert controller.active_engine == VoiceEngineType.GOOGLE_LIVE

print("\n" + "=" * 65)
print(">>> SESSION SPEND LIMIT VERIFIED: AUTO-DROP & BUDGET LOCKED <<<")
print("=" * 65)
