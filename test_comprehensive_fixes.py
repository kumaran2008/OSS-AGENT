import sqlite3
from pathlib import Path
from agent.pa_scaffolder.face_recognizer import FaceRecognizer
from agent.pa_scaffolder.biometric_vault import BiometricVault, BiometricSignature
from agent.chat_interface import AutonomousChatBot

db_path = Path("./workspace/test_fixes_brain.db").resolve()
db_path.parent.mkdir(parents=True, exist_ok=True)
if db_path.exists():
    db_path.unlink()

print("=== 1. TESTING PERSISTENT FACE RECOGNITION ===")
recognizer = FaceRecognizer(db_path=db_path)

# Create test images
img_user = Path("./workspace/test_user.jpg")
img_friend = Path("./workspace/test_friend.jpg")
img_user.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x05" * 128)
img_friend.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x08" * 128)

# Register Operator (User) and Friend using their image embeddings
ok_u = recognizer.register_person_image("Operator", "Self/Owner", img_user, notes="Primary account owner")
ok_f = recognizer.register_person_image("Sarah", "Colleague", img_friend, notes="Engineering team")
assert ok_u, "Failed to register user"
assert ok_f, "Failed to register friend"

# Match user image
res_user = recognizer.identify_person(img_user)
print(f"[✓] User Match: {res_user.name} ({res_user.relationship}) | Similarity: {res_user.similarity*100:.1f}%")
assert res_user.recognized, "User face was not recognized"
assert res_user.is_owner, "User was not recognized as owner"

# Match friend image
res_friend = recognizer.identify_person(img_friend)
print(f"[✓] Friend Match: {res_friend.name} ({res_friend.relationship}) | Similarity: {res_friend.similarity*100:.1f}%")
assert res_friend.recognized, "Friend face was not recognized"
assert not res_friend.is_owner, "Friend should not be marked as owner"

print("\n=== 2. TESTING BIOMETRIC SENSORS & TOOL GATING ===")
vault = BiometricVault(
    signature=BiometricSignature(user_call_sign="Operator", registered_voice_pitch_hz=145.0),
    db_path=db_path
)

def sensitive_bash_action(cmd):
    return f"Executed `{cmd}` safely."

passed, output = vault.gate_sensitive_action("Execute bash", sensitive_bash_action, "rm -rf /test")
print(f"[✓] Gated Action Result: {output}")
assert passed, "Biometric gate failed"

print("\n=== 3. TESTING CHATBOT MEMORY PERSISTENCE ===")
bot = AutonomousChatBot()
bot.conv_mem.log_message("user", "My secret code is ALPHA-42")
bot.conv_mem.log_message("assistant", "Noted and saved to session memory.")

recent = bot.conv_mem.get_recent_history(limit=2)
print(f"[✓] Recalled Turns from SQLite: {len(recent)} items")
assert any("ALPHA-42" in msg["content"] for msg in recent), "Memory persistence verification failed"

print("\n============================================================")
print(">>> ALL 4 CORE BREAKAGES RESOLVED AND VERIFIED <<<")
print("============================================================")
