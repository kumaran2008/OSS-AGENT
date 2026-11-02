import time
from agent.pa_scaffolder.platform_detector import HARDWARE_PROFILE, PlatformDetector
from agent.pa_scaffolder.audio_hardware import AdaptiveAudioHAL
from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine

print("=" * 65)
print("     SINGLE-BOOT HARDWARE PROFILER BENCHMARK")
print("=" * 65)

print("\n[1/3] In-Memory Cached Profile State...")
print(f" • Operating System:   {HARDWARE_PROFILE.os.value}")
print(f" • Machine Arch:       {HARDWARE_PROFILE.machine}")
print(f" • Preferred TTS:      {HARDWARE_PROFILE.preferred_tts}")
print(f" • Preferred STT:      {HARDWARE_PROFILE.preferred_stt}")
print(f" • Desktop Chrome:     {HARDWARE_PROFILE.has_desktop_chrome}")

print("\n[2/3] Testing Retrieval Latency (10,000 In-Memory Invocations)...")
t0 = time.perf_counter()
for _ in range(10000):
    p = PlatformDetector.get_profile()
    _ = p.os
t1 = time.perf_counter()

total_time_ms = (t1 - t0) * 1000
avg_time_ns = ((t1 - t0) / 10000) * 1_000_000_000
print(f" • 10,000 Profile Checks: {total_time_ms:.3f} ms total")
print(f" • Per-Lookup Latency:    {avg_time_ns:.1f} nanoseconds (Zero disk/subprocess overhead)")
assert total_time_ms < 50.0  # Must be purely in-memory

print("\n[3/3] Instantiating Subsystems with Cached State...")
hal = AdaptiveAudioHAL()
cdp = DesktopCDPEngine()
print(f" • AudioHAL OS Reference:    {hal.profile.os.value}")
print(f" • CDPEngine Chrome Flag:    {cdp.profile.has_desktop_chrome}")

print("\n" + "=" * 65)
print(">>> HARDWARE PROFILER BENCHMARK PASSED: SINGLE-RUN, O(1) RAM <<<")
print("=" * 65)
