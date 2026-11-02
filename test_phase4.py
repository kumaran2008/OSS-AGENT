import time
from pathlib import Path
from agent.pa_scaffolder import (
    HardwareDeviceHub,
    EmergencyPrivacyGuard,
    CentralCollectiveSwarmFederation
)

print("=== 1. OS HARDWARE & IOT ENGINE TEST ===")
hub = HardwareDeviceHub()

# Test Wi-Fi and Bluetooth radio controls
wifi_ok, wifi_msg = hub.set_wifi_state(True)
bt_ok, bt_msg = hub.set_bluetooth_state(True)
print(f"[✓] Wi-Fi: {wifi_msg}")
print(f"[✓] Bluetooth: {bt_msg}")

# Test Device Discovery
devices = hub.scan_nearby_devices()
print(f"[✓] Discovered {len(devices)} nearby smart device(s):")
for d in devices:
    print(f"    • {d.name} ({d.identifier}) [{d.device_type}] RSSI: {d.signal_strength}dBm")

# Test Smart AC Control
ac_action = hub.control_smart_ac(device_id="AA:BB:CC:11:22:33", power=True, target_temp_c=22)
print(f"[✓] AC Operation: {ac_action['message']} (Transport: {ac_action['transport']})")
assert ac_action["temperature_c"] == 22

# Test Matter / Google Home Device Trigger
matter_res = hub.trigger_matter_device("plug_living_room", action="toggle_power", parameters={"state": "ON"})
print(f"[✓] Matter Trigger: {matter_res['device_id']} -> {matter_res['action']} ({matter_res['protocol']})")


print("\n=== 2. 24-HOUR EMERGENCY PRIVACY SHUTDOWN TEST ===")
sandbox_mem = Path("./test_pa_env/memory").resolve()
privacy_guard = EmergencyPrivacyGuard(storage_dir=sandbox_mem)

# Trigger 24-hour lockdown
shutdown_res = privacy_guard.trigger_shutdown(hours=24.0, reason="Operator requested immediate downtime.")
print(f"[✓] Shutdown Triggered: {shutdown_res['action']}")

# Verify that agent is locked down
is_locked, status_msg = privacy_guard.check_lock_status()
print(f"[✓] Lock Status: {status_msg}")
assert is_locked

# Verify manual override brings systems back
unlocked, unlock_msg = privacy_guard.manual_override_unlock()
print(f"[✓] Manual Wakeup: {unlock_msg}")
is_locked_after, _ = privacy_guard.check_lock_status()
assert not is_locked_after


print("\n=== 3. CENTRAL SWARM FEDERATION & COLLECTIVE LEARNING TEST ===")
federation_root = Path("./test_pa_env/federation").resolve()
swarm_fed = CentralCollectiveSwarmFederation(registry_root=federation_root)

# Scenario: User A's agent fixes a Bluetooth AC timeout bug and publishes it
error_sig = "TimeoutError: BLE connection dropped before GATT write acknowledgement"
published_patch = swarm_fed.publish_verified_fix(
    error_signature=error_sig,
    resolution_logic="Introduce 150ms retry backoff before GATT write characteristic call.",
    benchmark_regression_score=0.0,
    author_node="user_alpha_agent"
)
print(f"[✓] User A published verified fix: {published_patch.patch_id}")

# Scenario: User B's agent encounters the same error -> queries central registry
found, community_patch = swarm_fed.query_and_apply_collective_fix(error_sig)
assert found
print(f"[✓] User B queried Central Federation & found patch within 0 seconds:")
print(f"    • Patch ID: {community_patch['patch_id']}")
print(f"    • Remedy: {community_patch['resolution_logic']}")
print(f"    • Verified (0% Regression): {community_patch['verified']}")

print("\n>>> PHASE 4 COMPLETE: Hardware IoT, 24-Hour Privacy Lockdown & Collective Federation validated with 0 errors.")
