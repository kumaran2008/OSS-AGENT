import time
from agent.pa_scaffolder.os_navigator import OSNavigator

nav = OSNavigator()
print("=" * 60)
print(f"[*] Driver Active: {nav.env.input_driver} | Resolution: {nav.screen_width}x{nav.screen_height}")
print("=" * 60)

# Step 1: Launch Search
print("\n[Step 1] Dispatching search intent for 'Madan Gowri'...")
ok, out = nav._execute_shell([
    "am", "start",
    "-a", "android.intent.action.SEARCH",
    "-p", "com.google.android.youtube",
    "-e", "query", "Madan Gowri"
])
print(f" -> Result: {'SUCCESS' if ok else 'FAILED'} | Output: {out}")

time.sleep(3.5)

# Step 2: Clear Soft Keyboard
print("\n[Step 2] Dismissing potential soft keyboard...")
ok_key = nav.press_key("BACK")
print(f" -> Back key dispatched: {ok_key}")
time.sleep(0.5)

# Step 3: Scroll Past Channel Header
print("\n[Step 3] Scrolling feed past profile header...")
ok_scroll = nav.scroll(direction="down", intensity=0.35)
print(f" -> Scroll gesture dispatched: {ok_scroll}")
time.sleep(1.5)

# Step 4: Tap Thumbnail
target_x = int(nav.screen_width * 0.50)
target_y = int(nav.screen_height * 0.45)
print(f"\n[Step 4] Tapping primary video at ({target_x}, {target_y})...")
ok_tap = nav.tap(target_x, target_y)
print(f" -> Tap dispatched: {ok_tap}")

print("\n" + "=" * 60)
print("[✓] Execution complete. Check the YouTube app on your screen.")
print("=" * 60)
