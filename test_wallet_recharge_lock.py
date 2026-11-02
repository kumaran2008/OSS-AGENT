from pathlib import Path
from agent.pa_scaffolder.hybrid_voice import (
    HybridVoiceController,
    PrepaidWalletManager,
    VoiceEngineType
)
from agent.pa_scaffolder.advanced_companion import AudioRoute

print("=" * 65)
print("     WALLET RECHARGE ISOLATION & ENGINE LOCK TEST")
print("=" * 65)

# 1. Initialize empty wallet
wallet = PrepaidWalletManager(wallet_path=Path("workspace/test_wallet_lock.json"))
wallet.data["balance_usd"] = 0.00
wallet._save()

controller = HybridVoiceController(wallet=wallet)

print("\n[1/4] Checking Initial State...")
print(f" • Initial Balance: ${wallet.balance:.2f}")
print(f" • Active Engine:   {controller.active_engine.value}")
assert controller.active_engine == VoiceEngineType.KOKORO_LOCAL

print("\n[2/4] Recharging Wallet with $25.00...")
wallet.top_up(25.00, reference="upi_test_recharge")
print(f" • New Balance:    ${wallet.balance:.2f}")
print(f" • Active Engine:   {controller.active_engine.value}")

# Proof: Engine MUST stay on Kokoro
assert controller.active_engine == VoiceEngineType.KOKORO_LOCAL
print(" • [CONFIRMED]: Engine remained strictly on Kokoro after recharge!")

print("\n[3/4] Running Normal Turn (No Switch Instruction)...")
# User interacts normally without asking for Google Live
res = controller.synthesize_and_dispatch("What is the plan today?", AudioRoute.EAR_ONLY)
print(f" • Engine Used:     {res['engine_used']} (Deducted: ${res['cost_deducted']:.2f})")
print(f" • Balance Left:    ${wallet.balance:.2f}")
assert res["engine_used"] == "kokoro_local"
assert res["cost_deducted"] == 0.00

print("\n[4/4] Issuing Explicit Voice Switch Command...")
cmd = "Hype, switch to Google Live API to speak"
switched, reply, _ = controller.process_voice_switch_command(cmd)
print(f" • Spoken Command: \"{cmd}\"")
print(f" • Switched:       {switched}")
print(f" • Active Engine:   {controller.active_engine.value}")
assert controller.active_engine == VoiceEngineType.GOOGLE_LIVE
assert switched is True

print("\n" + "=" * 65)
print(">>> PASSED: WALLET RECHARGE NEVER AUTO-SWITCHES TO PAID APIS <<<")
print("=" * 65)
