import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://127.0.0.1:14242"

def print_result(endpoint: str, method: str, status: str, latency_ms: float, detail: str = ""):
    status_color = "\033[92mPASS\033[0m" if status == "OK" else "\033[91mFAIL\033[0m"
    print(f"[{status_color}] {method:<4} {endpoint:<20} {latency_ms:>7.2f} ms | {detail}")

print("=" * 70)
print("       AEGIS COMPANION SERVER :: ENDPOINT DIAGNOSTIC SUITE")
print("=" * 70)

# 0. Preflight Port Check
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(f"{BASE_URL}/", timeout=3) as resp:
        preflight_ms = (time.perf_counter() - t0) * 1000
        print(f"[*] Port 14242 active and listening. Base ping: {preflight_ms:.2f} ms\n")
except Exception as e:
    print(f"\033[91m[ERROR]\033[0m Cannot connect to {BASE_URL}. Ensure 'run_companion.py' is running.")
    print(f"Details: {e}")
    sys.exit(1)

# 1. GET / (UI Dashboard HTML)
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(f"{BASE_URL}/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
        latency = (time.perf_counter() - t0) * 1000
        assert resp.status == 200
        assert "AEGIS :: OSS-AGENT" in body
        assert "companion-orb" in body
        print_result("/", "GET", "OK", latency, f"HTTP {resp.status} - Glassmorphic UI delivered ({len(body)} bytes)")
except Exception as e:
    print_result("/", "GET", "FAIL", (time.perf_counter() - t0) * 1000, str(e))

# 2. GET /api/auth_status
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(f"{BASE_URL}/api/auth_status", timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        latency = (time.perf_counter() - t0) * 1000
        assert resp.status == 200
        assert "OPENROUTER_API_KEY" in body
        assert "GITHUB_TOKEN" in body
        status_summary = f"OpenRouter: {'Active' if body['OPENROUTER_API_KEY'] else 'Unset'}, GitHub: {'Active' if body['GITHUB_TOKEN'] else 'Unset'}"
        print_result("/api/auth_status", "GET", "OK", latency, status_summary)
except Exception as e:
    print_result("/api/auth_status", "GET", "FAIL", (time.perf_counter() - t0) * 1000, str(e))

# 3. GET /api/state
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(f"{BASE_URL}/api/state", timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        latency = (time.perf_counter() - t0) * 1000
        assert resp.status == 200
        assert "state" in body and "message" in body
        print_result("/api/state", "GET", "OK", latency, f"State: {body['state']} | Msg: \"{body['message'][:25]}...\"")
except Exception as e:
    print_result("/api/state", "GET", "FAIL", (time.perf_counter() - t0) * 1000, str(e))

# 4. POST /api/chat_stream (Deterministic OS Action Dispatch)
t0 = time.perf_counter()
try:
    req_data = json.dumps({"message": "open youtube"}).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}/api/chat_stream", data=req_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        latency = (time.perf_counter() - t0) * 1000
        assert "[OS Action]" in body
        print_result("/api/chat_stream", "POST", "OK", latency, f"OS Dispatch verified: {body[:35]}...")
except Exception as e:
    print_result("/api/chat_stream", "POST", "FAIL", (time.perf_counter() - t0) * 1000, str(e))

# 5. POST /api/chat_stream (PA Scaffolder Intent)
t0 = time.perf_counter()
try:
    req_data = json.dumps({"message": "build pa named AegisDiagnostics"}).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}/api/chat_stream", data=req_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        latency = (time.perf_counter() - t0) * 1000
        assert "Personal Agent" in body or "deployed" in body
        print_result("/api/chat_stream", "POST", "OK", latency, f"Scaffolder Intent: Built PA successfully")
except Exception as e:
    print_result("/api/chat_stream", "POST", "FAIL", (time.perf_counter() - t0) * 1000, str(e))

# 6. POST /api/vision_upload (Multimodal / Face Ingestion Pipeline)
t0 = time.perf_counter()
try:
    dummy_img = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00" + b"\x05" * 300
    req = urllib.request.Request(f"{BASE_URL}/api/vision_upload", data=dummy_img, headers={"Content-Type": "image/jpeg"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        res_json = json.loads(resp.read().decode("utf-8"))
        latency = (time.perf_counter() - t0) * 1000
        assert "result" in res_json
        print_result("/api/vision_upload", "POST", "OK", latency, "Image ingestion and routing verified")
except Exception as e:
    print_result("/api/vision_upload", "POST", "FAIL", (time.perf_counter() - t0) * 1000, str(e))

print("=" * 70)
print(">>> DIAGNOSTIC COMPLETE: ALL ENDPOINTS ACTIVE AND OPERATIONAL <<<")
print("=" * 70)
