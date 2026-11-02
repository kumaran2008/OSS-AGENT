from agent.pa_scaffolder.os_navigator import OSNavigator

print("=" * 65)
print("     ADAPTIVE OS NAVIGATOR :: HARDWARE & OS PROBE")
print("=" * 65)

nav = OSNavigator()
env = nav.env

print(f" • Detected OS Family:     {env.os_family.upper()}")
print(f" • Display Server:         {env.display_server}")
print(f" • Input Execution Driver: {env.input_driver}")
print(f" • Is Android Environment: {env.is_android}")
print(f" • Has Root Privileges:    {env.has_root}")
print(f" • Has Rish / Shizuku:     {env.has_rish}")
print(f" • Has Termux:API Tooling: {env.has_termux_api}")
print(f" • Screen Dimensions:      {env.screen_width} x {env.screen_height}")

print("\n[*] Testing input fallbacks across detected tier...")
ok_tap = nav.tap(500, 500)
print(f" • Tap Dispatch:    {'PASS' if ok_tap else 'FAIL'}")

ok_scroll = nav.scroll("down", intensity=0.3)
print(f" • Scroll Dispatch: {'PASS' if ok_scroll else 'FAIL'}")

ok_key = nav.press_key("BACK")
print(f" • Key Dispatch:    {'PASS' if ok_key else 'FAIL'}")

ok_app, msg = nav.open_app("youtube")
print(f" • App Launch:      {msg}")

print("\n" + "=" * 65)
print(">>> ADAPTIVE OS NAVIGATOR FULLY INITIALIZED <<<")
print("=" * 65)
