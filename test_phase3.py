import sqlite3
from pathlib import Path
from agent.pa_scaffolder import (
    StreamingVoiceEngine,
    VoiceProfile,
    BiometricVault,
    BiometricSignature,
    MultimodalVisionEngine
)

print("=== 1. ZERO-LAG VOICE ENGINE TEST ===")
voice = StreamingVoiceEngine()
# Test audio packet synthesis with upbeat and calm modulation
pkt_upbeat = voice.synthesize_chunk("Tests passed!", emotion="upbeat")
pkt_calm = voice.synthesize_chunk("Warning detected.", emotion="calm")
print(f"[✓] Upbeat audio chunk generated: {pkt_upbeat.decode('utf-8')}")
print(f"[✓] Calm audio chunk generated: {pkt_calm.decode('utf-8')}")
voice.speak("Hype is ready to serve you daily.", emotion="upbeat")

print("\n=== 2. BIOMETRIC VAULT TEST (SINGLE FACTOR: FACE OR VOICE) ===")
vault = BiometricVault()

# Test A: Accurate Face sample alone
face_ok, msg = vault.authenticate(face_sample=[0.12, 0.45, 0.78, 0.91, 0.33, 0.65, 0.82, 0.50])
print(f"[✓] Test A (Accurate Face): {msg}")
assert face_ok

# Test B: Accurate Voice sample alone (with unrecognized face)
voice_ok, msg = vault.authenticate(
    face_sample=[0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99], # bad face
    voice_sample=(146.2, [510.0, 1490.0, 2520.0])                  # valid voice
)
print(f"[✓] Test B (Valid Voice over bad face): {msg}")
assert voice_ok

# Test C: Both invalid
denied_ok, msg = vault.authenticate(
    face_sample=[0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
    voice_sample=(220.0, [900.0, 2100.0, 3100.0])
)
print(f"[✓] Test C (Both Invalid): {msg}")
assert not denied_ok

print("\n=== 3. MULTIMODAL VISION & NUTRITION ENGINE TEST ===")
db_path = Path("./test_pa_env/memory/brain.db").resolve()
assert db_path.exists(), "test_pa_env/memory/brain.db must exist from phase 1 test."
vision = MultimodalVisionEngine(db_path=db_path)

# Log and estimate food
nutri = vision.analyze_food_photo("Grilled chicken breast and salad plate")
print(f"[✓] Food Parsed: {nutri.food_item} | Calories: {nutri.calories} kcal | Protein: {nutri.protein_g}g")

# Check persistence in brain.db
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT food_item, calories, protein_g FROM daily_nutrition ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
conn.close()
print(f"[✓] Verified in SQLite brain.db: {row[0]} -> {row[1]} kcal, {row[2]}g protein")
assert row[0] == nutri.food_item

# Test Person Photo Detection
person_result = vision.analyze_person_photo("Kumaran", "Colleague / Engineer", is_user_self=False)
print(f"[✓] Person Ingested: {person_result['detected']} -> {person_result['action_prompt']}")

print("\n>>> PHASE 3 VERIFICATION PASSED: Voice, Biometrics & Vision Engines validated with 0 errors.")
