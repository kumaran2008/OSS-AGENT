from agent.pa_scaffolder.os_navigator import OSNavigator

print("=== 1. INITIALIZING CROSS-OS NAVIGATOR ===")
nav = OSNavigator()
print(f"[✓] Navigator active (Platform: {'Termux/Android' if nav.is_termux else 'Desktop'})")
print(f"[✓] Screen Resolution detected: {nav.screen_width}x{nav.screen_height}")

print("\n=== 2. TESTING SCROLL SIMULATION ===")
ok_scroll = nav.scroll("down", intensity=0.4)
print(f"[✓] Scroll gesture executed: {ok_scroll}")
assert ok_scroll

print("\n=== 3. TESTING HARDWARE KEY DISPATCH ===")
ok_key = nav.press_key("BACK")
print(f"[✓] Keyevent dispatch executed: {ok_key}")
assert ok_key

print("\n=== 4. TESTING APP RESOLVER ===")
# Verify app mapping contains standard targets
assert "youtube" in nav.ANDROID_APP_MAP
assert "keyboard" in nav.ANDROID_APP_MAP
print(f"[✓] Verified Android app package resolver ({len(nav.ANDROID_APP_MAP)} packages cataloged).")

print("\n============================================================")
print(">>> OS INTERACTION & GESTURE NAVIGATION VERIFIED <<<")
print("============================================================")
