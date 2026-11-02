import os
import platform
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

KNOWN_APP_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "freefire": {
        "name": "Garena Free Fire",
        "min_storage_mb": 3500,
        "min_ram_mb": 2048,
        "supported_abi": ["arm64-v8a", "armeabi-v7a"],
        "target_platform": "android",
    },
    "mario": {
        "name": "Super Mario Bros (NES)",
        "min_storage_mb": 150,
        "min_ram_mb": 512,
        "supported_abi": ["any"],
        "target_platform": "any",
    },
}


class SystemAuditor:
    """Inspects device specs and evaluates whether target apps/games can run safely."""

    def __init__(self, adb_target: Optional[str] = None):
        self.adb_target = adb_target

    def _run_cmd(self, cmd: list) -> str:
        if self.adb_target:
            full_cmd = ["adb", "-s", self.adb_target, "shell"] + cmd
        else:
            full_cmd = cmd
        res = subprocess.run(full_cmd, capture_output=True, text=True)
        return res.stdout.strip()

    def get_hardware_specs(self) -> Dict[str, Any]:
        """Returns storage, RAM, and architecture specs."""
        # 1. Available Storage
        total_storage_mb, free_storage_mb = 0, 0
        try:
            total, used, free = shutil.disk_usage(os.getcwd())
            total_storage_mb = total // (1024 * 1024)
            free_storage_mb = free // (1024 * 1024)
        except Exception:
            pass

        # 2. Available RAM
        total_ram_mb = 0
        try:
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            total_ram_mb = int(line.split()[1]) // 1024
                            break
        except Exception:
            pass

        # 3. CPU Architecture / ABI
        abi = "unknown"
        if self.adb_target:
            abi = self._run_cmd(["getprop", "ro.product.cpu.abi"])
        if not abi or abi == "unknown":
            abi = platform.machine()

        return {
            "platform": platform.system().lower(),
            "cpu_arch": abi,
            "total_ram_mb": total_ram_mb,
            "free_storage_mb": free_storage_mb,
            "total_storage_mb": total_storage_mb,
        }

    def verify_app_compatibility(self, app_key: str) -> Tuple[bool, str]:
        """Verifies if the device meets the hardware spec for an app/game."""
        specs = self.get_hardware_specs()
        reqs = KNOWN_APP_REQUIREMENTS.get(app_key.lower())

        if not reqs:
            # Fallback general safety check: minimum 500MB free storage
            if specs["free_storage_mb"] < 500:
                return False, f"Low disk space: Only {specs['free_storage_mb']}MB free. Aborting download."
            return True, "Standard requirements met."

        # Check Storage
        if specs["free_storage_mb"] < reqs["min_storage_mb"]:
            return False, (
                f"Storage Inadequate: '{reqs['name']}' requires at least {reqs['min_storage_mb']}MB, "
                f"but only {specs['free_storage_mb']}MB is available. Download would fail."
            )

        # Check RAM if available
        if specs["total_ram_mb"] > 0 and specs["total_ram_mb"] < reqs["min_ram_mb"]:
            return False, (
                f"RAM Inadequate: '{reqs['name']}' requires {reqs['min_ram_mb']}MB RAM, "
                f"device only has {specs['total_ram_mb']}MB."
            )

        return True, f"Hardware compatible with {reqs['name']}."
