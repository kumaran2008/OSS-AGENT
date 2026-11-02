import random
from agent.pa_scaffolder.vision_identity import BiometricVisionIdentity
from agent.pa_scaffolder.graph_brain import GraphBrainDB

print("=" * 65)
print("     BIOMETRIC VISION IDENTITY & PRESENCE TEST")
print("=" * 65)

brain = GraphBrainDB()
verifier = BiometricVisionIdentity(brain=brain)

# 1. Generate synthetic deterministic 64-d face embedding for Operator
random.seed(42)
master_face = [random.uniform(-1.0, 1.0) for _ in range(64)]

print("\n[1/4] Enrolling Operator Master Face Geometry...")
ok, enroll_msg = verifier.enroll_master_face(master_face)
print(f" • Enrollment: {enroll_msg}")
assert ok is True
assert verifier.get_enrolled_face() is not None

print("\n[2/4] Verifying Genuine Operator Match (Slight Lighting Jitter)...")
# Add minor sensor noise (+- 5%)
sensor_noisy_face = [x + random.uniform(-0.04, 0.04) for x in master_face]
is_auth, score, auth_msg = verifier.verify_operator_identity(sensor_noisy_face)
print(f" • Result: {auth_msg}")
assert is_auth is True
assert score >= 0.85

print("\n[3/4] Testing Intruder / Imposter Rejection...")
# Completely different face vector
intruder_face = [random.uniform(-1.0, 1.0) for _ in range(64)]
is_auth_bad, bad_score, bad_msg = verifier.verify_operator_identity(intruder_face)
print(f" • Result: {bad_msg}")
assert is_auth_bad is False
assert bad_score < 0.70

print("\n[4/4] Testing Ambient Presence & Shoulder-Surfer Detection...")
# Scenario A: Operator left room (0 faces)
away_status = verifier.evaluate_presence(detected_faces_count=0, primary_vector=None)
print(f" • Empty Desk: Present={away_status['operator_present']} | Whisper=\"{away_status['status_whisper']}\"")
assert away_status["operator_present"] is False

# Scenario B: Multiple faces (Shoulder surfer / Anti-Dox)
crowd_status = verifier.evaluate_presence(detected_faces_count=2, primary_vector=sensor_noisy_face)
print(f" • Multiple Faces: Alert={crowd_status['shoulder_surfer_alert']} | Action=\"{crowd_status['status_whisper']}\"")
assert crowd_status["shoulder_surfer_alert"] is True
assert crowd_status["privacy_guard_recommended"] is True

print("\n" + "=" * 65)
print(">>> BIOMETRIC IDENTITY & PRESENCE SENTINEL 100% OPERATIONAL <<<")
print("=" * 65)
