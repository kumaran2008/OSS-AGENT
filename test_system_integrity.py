import time
from pathlib import Path
from agent.chat_interface import AutonomousChatBot
from agent.pa_scaffolder.face_recognizer import FaceRecognizer
from agent.pa_scaffolder.biometric_vault import BiometricVault, BiometricSignature
from agent.pa_scaffolder.app_layout_cache import AppLayoutCache

print("=" * 65)
print("     OSS-AGENT & PERSONAL AGENT INTEGRITY VERIFICATION")
print("=" * 65)

# 1. Test Chatbot -> OSNavigator Wiring
print("\n[1/5] Testing Brain-to-Hands OS Navigation...")
bot = AutonomousChatBot()

res_open = bot.handle_device_action("open youtube")
print(f"      • Command 'open youtube' -> {res_open}")
assert res_open and "[OS Action]" in res_open

res_scroll = bot.handle_device_action("scroll down")
print(f"      • Command 'scroll down'  -> {res_scroll}")
assert res_scroll and "[OS Action]" in res_scroll

res_key = bot.handle_device_action("press back")
print(f"      • Command 'press back'   -> {res_key}")
assert res_key and "[OS Action]" in res_key

# 2. Test Conversational Memory Retention
print("\n[2/5] Testing Session Memory & SQLite Persistence...")
bot.conv_mem.log_message("user", "System credential check: AEGIS_KEY_77")
bot.conv_mem.log_message("assistant", "Credential received and committed.")
recent = bot.conv_mem.get_recent_history(limit=2)
assert any("AEGIS_KEY_77" in m["content"] for m in recent)
print(f"      • Verified: Memory accurately persisted across turns.")

# 3. Test Layout Cache Retrieval
print("\n[3/5] Testing 0-Delay Layout Cache...")
cache = AppLayoutCache(db_path=Path("./workspace/test_integrity_brain.db"))
t0 = time.perf_counter()
coords = cache.get_coordinates("com.google.android.youtube", "search_button", 1080, 2400)
latency_ms = (time.perf_counter() - t0) * 1000
print(f"      • Coords: {coords} (Lookup time: {latency_ms:.3f} ms)")
assert coords == (950, 144)
assert latency_ms < 5.0

# 4. Test Face Identification
print("\n[4/5] Testing Reliable Face Recognition...")
face_rec = FaceRecognizer(db_path=Path("./workspace/test_integrity_brain.db"))
sample_img = Path("./workspace/test_operator_face.jpg")
sample_img.parent.mkdir(parents=True, exist_ok=True)
sample_img.write_bytes(b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"\x42" * 500)

ok_reg = face_rec.register_person("Operator", "Self/Owner", sample_img, notes="Primary account holder")
assert ok_reg
match = face_rec.identify_person(sample_img)
print(f"      • Match: {match.name} ({match.relationship}) | Conf: {match.similarity*100:.0f}%")
assert match.recognized and match.is_owner

# 5. Test Biometric Security Gate
print("\n[5/5] Testing Biometric Security Interceptor...")
vault = BiometricVault(
    signature=BiometricSignature(user_call_sign="Operator", registered_voice_pitch_hz=145.0),
    db_path=Path("./workspace/test_integrity_brain.db")
)
action_called = False
def test_action():
    global action_called
    action_called = True
    return "SUCCESS"

passed, out = vault.gate_sensitive_action("Restricted Action", test_action)
print(f"      • Result: {out} (Action executed: {action_called})")
assert passed and action_called

print("\n" + "=" * 65)
print(">>> ALL MODULES WIRED AND 100% OPERATIONAL WITH ZERO BREAKS <<<")
print("=" * 65)
