import time
from agent.pa_scaffolder.os_navigator import OSNavigator

nav = OSNavigator()
print("[*] Launching Madan Gowri channel via Android Intent...")

# 1. Open the channel videos tab directly
nav._execute_shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", "https://www.youtube.com/@madangowri/videos"])

# Wait for YouTube to load the video grid
time.sleep(2.5)

# 2. Tap the first video (latest upload at top of grid)
# Normalized coordinate for the first video thumbnail
first_video_x = int(nav.screen_width * 0.50)
first_video_y = int(nav.screen_height * 0.32)

print(f"[*] Tapping latest video at ({first_video_x}, {first_video_y})...")
nav.tap(first_video_x, first_video_y)
print("[✓] Video playing.")
