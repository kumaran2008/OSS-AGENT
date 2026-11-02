import time
import sys
from agent.pa_scaffolder.ui_server import FloatingCompanionServer
from agent.pa_scaffolder.native_window import NativeCompanionWindow

# Initialize and start streaming HTTP server
server = FloatingCompanionServer(port=14242)
server.start()

url = "http://127.0.0.1:14242"
print("\n" + "=" * 60)
print("      AEGIS PERSONAL AGENT :: COMPANION SERVER ONLINE")
print("=" * 60)
print(f" • Local Web Interface:  {url}")
print(f" • Alternative Loopback: http://localhost:14242")
print("=" * 60)

# Dispatch native browser / Termux overlay window
window = NativeCompanionWindow(port=14242)
window.launch(block=False)

print("\nServer is running. Press Ctrl+C to shut down.\n")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[!] Companion server stopped.")
