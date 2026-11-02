from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine, AgentMode
from agent.pa_scaffolder.hybrid_voice import VoiceEngineType

print("=" * 65)
print("     ENGINE HARNESS DYNAMIC VOICE LIMIT VERIFICATION")
print("=" * 65)

harness = UnifiedAsyncEngine(default_mode=AgentMode.NORMAL)
# Top up wallet with funds
harness.wallet.top_up(10.00, reference="test_topup")

print("\n[1/5] Testing Spoken Limit Command via Harness...")
res_lim = harness.process_voice_turn("hey hype set cloud voice limit to 2 dollars")
print(f" • Response Type:    {res_lim['type']}")
print(f" • Spoken Response:  \"{res_lim['spoken_response']}\"")
print(f" • Configured Limit: ${res_lim['session_spend_limit']:.2f}")
assert res_lim["type"] == "VOICE_ENGINE_COMMAND"
assert res_lim["session_spend_limit"] == 2.00
assert harness.voice_controller.session_spend_limit == 2.00

print("\n[2/5] Switching to Google Live via Voice Command...")
res_switch = harness.process_voice_turn("bro use google live api to speak")
print(f" • Spoken Response:  \"{res_switch['spoken_response']}\"")
print(f" • Active Engine:    {res_switch['audio_engine']}")
assert res_switch["audio_engine"] == "google_live"
assert harness.voice_controller.active_engine == VoiceEngineType.GOOGLE_LIVE

print("\n[3/5] Lowering Limit Dynamically to Trigger Fast Auto-Drop...")
# Adjust limit down to $0.005 (just enough for ~2 turns)
harness.process_voice_turn("set cloud voice limit to 0.005 dollars")
print(f" • New Session Limit: ${harness.voice_controller.session_spend_limit:.4f}")

# Turn 1: 0.002
t1 = harness.process_voice_turn("can I buy hot wings or bucket in kfc")
print(f" • Turn 1: Engine={t1['audio_engine']} | Spent=${t1['session_spent_usd']:.4f}")
assert t1["audio_engine"] == "google_live"

# Turn 2: 0.004
t2 = harness.process_voice_turn("can I buy hot wings or bucket in kfc")
print(f" • Turn 2: Engine={t2['audio_engine']} | Spent=${t2['session_spent_usd']:.4f}")
assert t2["audio_engine"] == "google_live"

# Turn 3: Would hit 0.006 -> Must trigger auto-drop back to Kokoro
t3 = harness.process_voice_turn("can I buy hot wings or bucket in kfc")
print(f" • Turn 3: Engine={t3['audio_engine']} | Spent=${t3['session_spent_usd']:.4f}")
print(f" • Notice Attached:   \"{t3['notice']}\"")
assert t3["audio_engine"] == "kokoro_local"
assert harness.voice_controller.active_engine == VoiceEngineType.KOKORO_LOCAL

print("\n[4/5] Verifying Blocked Re-Switch When Cap Is Hit...")
res_blocked = harness.process_voice_turn("switch to google live api")
print(f" • Spoken Explanation: \"{res_blocked['spoken_response']}\"")
assert res_blocked["action_success"] is False
assert "Staying on local Kokoro" in res_blocked["spoken_response"]

print("\n[5/5] Resetting Session Spend Counter via Voice...")
res_reset = harness.process_voice_turn("reset cloud voice spend")
print(f" • Spoken Response: \"{res_reset['spoken_response']}\"")
assert harness.voice_controller.session_spent_usd == 0.00

# Re-switch succeeds now
res_reswitch = harness.process_voice_turn("use google live api to speak")
print(f" • Re-switch: {res_reswitch['audio_engine']}")
assert res_reswitch["audio_engine"] == "google_live"

print("\n" + "=" * 65)
print(">>> ENGINE HARNESS DYNAMIC LIMITS 100% OPERATIONAL & VERIFIED <<<")
print("=" * 65)
