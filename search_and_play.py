import time
from agent.pa_scaffolder.os_navigator import OSNavigator

nav = OSNavigator()

print("[1/5] Opening YouTube App...")
nav.open_app("youtube")
time.sleep(2.0)

print("[2/5] Clicking Search Button...")
nav.click_element("youtube", "search_button")
time.sleep(1.0)

print("[3/5] Typing Search Query: 'Madan Gowri'...")
nav.type_text("Madan Gowri")
time.sleep(0.8)

print("[4/5] Submitting Search...")
nav.press_key("ENTER")
time.sleep(2.0)

print("[5/5] Clicking First Result...")
nav.click_element("youtube", "first_video")
print("[✓] Latest video opened.")
