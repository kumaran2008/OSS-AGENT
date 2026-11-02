import sys
import time
import json
import urllib.request
from agent.pa_scaffolder.ui_server import FloatingCompanionServer

TEST_PORT = 14243
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

print("=" * 70)
print("   AEGIS COMPANION SERVER :: INTEGRATED VERIFICATION")
print("=" * 70)

# 1. Start Multi-Threaded Server
server = FloatingCompanionServer(port=TEST_PORT)
server.start()
time.sleep(0.5)

def print_row(endpoint, method, status, latency_ms, detail):
    col = "\033[92mPASS\033[0m" if status == "OK" else "\033[91mFAIL\033[0m"
    print(f"[{col}] {method:<4} {endpoint:<20} {latency_ms:>7.2f} ms | {detail}")

# 2. Test GET /
t0 = time.perf_counter()
with urllib.request.urlopen(f"{BASE_URL}/", timeout=3) as resp:
    body = resp.read().decode("utf-8")
    print_row("/", "GET", "OK", (time.perf_counter() - t0) * 1000, f"HTTP {resp.status} ({len(body)} bytes)")

# 3. Test GET /api/auth_status
t0 = time.perf_counter()
with urllib.request.urlopen(f"{BASE_URL}/api/auth_status", timeout=3) as resp:
    body = json.loads(resp.read().decode("utf-8"))
    print_row("/api/auth_status", "GET", "OK", (time.perf_counter() - t0) * 1000, f"Credentials checked: {list(body.keys())}")

# 4. Test GET /api/state
t0 = time.perf_counter()
with urllib.request.urlopen(f"{BASE_URL}/api/state", timeout=3) as resp:
    body = json.loads(resp.read().decode("utf-8"))
    print_row("/api/state", "GET", "OK", (time.perf_counter() - t0) * 1000, f"State: {body['state']}")

# 5. Test POST /api/chat_stream (OS Action)
t0 = time.perf_counter()
req_data = json.dumps({"message": "open youtube"}).encode("utf-8")
req = urllib.request.Request(f"{BASE_URL}/api/chat_stream", data=req_data, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=5) as resp:
    body = resp.read().decode("utf-8", errors="replace")
    assert "[OS Action]" in body
    print_row("/api/chat_stream", "POST", "OK", (time.perf_counter() - t0) * 1000, f"Response: {body[:32]}...")

# 6. Test POST /api/chat_stream (PA Scaffolder)
t0 = time.perf_counter()
req_data = json.dumps({"message": "build pa named AegisDirect"}).encode("utf-8")
req = urllib.request.Request(f"{BASE_URL}/api/chat_stream", data=req_data, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=5) as resp:
    body = resp.read().decode("utf-8", errors="replace")
    assert "Personal Agent" in body or "deployed" in body
    print_row("/api/chat_stream", "POST", "OK", (time.perf_counter() - t0) * 1000, "Scaffolding Intent Verified")

# 7. Test POST /api/vision_upload
t0 = time.perf_counter()
dummy_img = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00" + b"\x42" * 200
req = urllib.request.Request(f"{BASE_URL}/api/vision_upload", data=dummy_img, headers={"Content-Type": "image/jpeg"})
with urllib.request.urlopen(req, timeout=5) as resp:
    body = json.loads(resp.read().decode("utf-8"))
    assert "result" in body
    print_row("/api/vision_upload", "POST", "OK", (time.perf_counter() - t0) * 1000, "Vision Upload Verified")

print("=" * 70)
print(">>> ALL ENDPOINTS PASS INTEGRITY VERIFICATION <<<")
print("=" * 70)
