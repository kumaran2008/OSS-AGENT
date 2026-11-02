import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, List

HIGH_RISK_PERMISSIONS = {
    "android.permission.BIND_ACCESSIBILITY_SERVICE": "Can intercept, monitor, and control screen interactions.",
    "android.permission.RECEIVE_SMS": "Can intercept 2FA verification codes and private text messages.",
    "android.permission.READ_SMS": "Can read private SMS communications.",
    "android.permission.READ_CALL_LOG": "Can monitor incoming and outgoing call records.",
    "android.permission.REQUEST_INSTALL_PACKAGES": "Can silently download and install secondary malicious packages.",
    "android.permission.SYSTEM_ALERT_WINDOW": "Can draw invisible overlays over banking and login screens.",
}


class SafetyScanner:
    """Inspects downloaded artifacts and APK files for security threats and excessive permissions."""

    @staticmethod
    def audit_apk_file(apk_path: Path) -> Dict[str, Any]:
        if not apk_path.exists():
            return {"safe": False, "error": f"File not found: {apk_path}"}

        # 1. Check basic file integrity
        if not zipfile.is_zipfile(apk_path):
            return {"safe": False, "error": "Corrupt file: Not a valid Android package archive."}

        permissions_found: List[str] = []
        flagged_risks: Dict[str, str] = {}

        # 2. Try inspection via aapt/aapt2 if available on system
        try:
            res = subprocess.run(["aapt", "dump", "permissions", str(apk_path)], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    if "uses-permission:" in line or "permission:" in line:
                        perm = line.split("name=")[-1].strip("'\" \t\r\n")
                        permissions_found.append(perm)
        except Exception:
            pass

        # 3. Fallback: inspect raw binary AndroidManifest.xml strings
        if not permissions_found:
            try:
                with zipfile.ZipFile(apk_path, "r") as z:
                    manifest_data = z.read("AndroidManifest.xml")
                    for high_perm in HIGH_RISK_PERMISSIONS:
                        if high_perm.encode("utf-8") in manifest_data:
                            permissions_found.append(high_perm)
            except Exception:
                pass

        # 4. Evaluate against known threat vectors
        for p in permissions_found:
            for risk_perm, reason in HIGH_RISK_PERMISSIONS.items():
                if risk_perm.lower() in p.lower():
                    flagged_risks[risk_perm] = reason

        is_safe = len(flagged_risks) == 0
        return {
            "safe": is_safe,
            "permissions_detected": permissions_found,
            "high_risk_flags": flagged_risks,
            "verdict": "CLEAN" if is_safe else "HIGH_RISK_WARNING",
        }
