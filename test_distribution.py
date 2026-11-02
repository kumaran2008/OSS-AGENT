import os
import subprocess
from pathlib import Path
from agent.pa_scaffolder import NativeCompanionWindow

print("=== 1. TESTING NATIVE WINDOW CONTROLLER ===")
window = NativeCompanionWindow(port=14242)
assert window.port == 14242
assert window.url == "http://127.0.0.1:14242"
print(f"[✓] NativeCompanionWindow created successfully (Target URL: {window.url})")

print("\n=== 2. VERIFYING INSTALLER SCRIPT ===")
installer = Path("./install.sh")
assert installer.exists(), "install.sh is missing!"
assert os.access(installer, os.X_OK), "install.sh is not executable!"
print(f"[✓] install.sh verified: executable bit set.")

# Execute installer dry-run
res = subprocess.run(["./install.sh"], capture_output=True, text=True)
print(res.stdout.strip())
assert res.returncode == 0, f"Installer failed with error:\n{res.stderr}"

print("\n============================================================")
print(">>> PRODUCT DISTRIBUTION ENGINE DEPLOYED SUCCESSFULLY <<<")
print("============================================================")
