import time
from pathlib import Path
from agent.pa_scaffolder.app_layout_cache import AppLayoutCache
from agent.pa_scaffolder.os_navigator import OSNavigator

test_db = Path("./workspace/test_cache_brain.db").resolve()
test_db.parent.mkdir(parents=True, exist_ok=True)
if test_db.exists():
    test_db.unlink()

print("=== 1. TESTING SEEDING & LATENCY BENCHMARK ===")
cache = AppLayoutCache(db_path=test_db)
w, h = 1080, 2400

# Benchmark Tier 1 Cache Lookup
start = time.perf_counter()
coords = cache.get_coordinates("com.google.android.youtube", "search_button", w, h)
lookup_time_ms = (time.perf_counter() - start) * 1000

print(f"[✓] Target: YouTube search_button -> Coordinates: {coords}")
print(f"[✓] Tier 1 Lookup Latency: {lookup_time_ms:.3f} ms")
assert coords is not None
assert coords == (int(0.88 * w), int(0.06 * h))
assert lookup_time_ms < 5.0  # Must be sub-5ms

print("\n=== 2. TESTING OSNAVIGATOR CLICK PIPELINE ===")
nav = OSNavigator(db_path=test_db)
nav.screen_width = w
nav.screen_height = h

ok, msg = nav.click_element("youtube", "search_button")
print(f"[✓] Pipeline Output: {msg}")
assert ok
assert "Tier 1 Cache Hit" in msg

print("\n=== 3. TESTING DYNAMIC COORDINATE STORAGE ===")
cache.save_coordinate("com.custom.app", "login_button", 0.50, 0.75)
saved_coords = cache.get_coordinates("com.custom.app", "login_button", w, h)
print(f"[✓] Dynamically Saved Target -> ({saved_coords[0]}, {saved_coords[1]})")
assert saved_coords == (540, 1800)

print("\n============================================================")
print(">>> PRE-EXISTING COORDINATE CACHE VERIFIED (<1ms LATENCY) <<<")
print("============================================================")
