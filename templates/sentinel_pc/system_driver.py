import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List, Optional

DANGEROUS_COMMAND_PATTERNS = [
    "rm -rf /",
    "mkfs",
    ":(){ :|:& };:",
    "> /dev/sda",
    "dd if=",
    "shutdown",
    "reboot",
]


class SystemDriver:
    """Manages local OS command execution, process monitoring, and system metrics."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.getcwd())

    def get_system_specs(self) -> Dict[str, Any]:
        """Audits CPU, RAM, disk headroom, and OS details."""
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

        total_storage_mb, free_storage_mb = 0, 0
        try:
            total, used, free = shutil.disk_usage(self.workspace_root)
            total_storage_mb = total // (1024 * 1024)
            free_storage_mb = free // (1024 * 1024)
        except Exception:
            pass

        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "cpu_arch": platform.machine(),
            "total_ram_mb": total_ram_mb,
            "free_storage_mb": free_storage_mb,
            "total_storage_mb": total_storage_mb,
        }

    def run_command(self, cmd: str, timeout: int = 45) -> Dict[str, Any]:
        """Runs a shell command and captures returncode, stdout, and stderr."""
        for pattern in DANGEROUS_COMMAND_PATTERNS:
            if pattern in cmd:
                return {
                    "success": False,
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"BLOCKED: Command contains destructive pattern '{pattern}'",
                }

        try:
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": res.returncode == 0,
                "returncode": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds.",
            }
        except Exception as e:
            return {"success": False, "returncode": -1, "stdout": "", "stderr": str(e)}

    def list_processes(self, filter_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries running processes using standard ps utility."""
        res = subprocess.run(["ps", "-eo", "pid,comm,%cpu,%mem"], capture_output=True, text=True)
        if res.returncode != 0:
            return []

        lines = res.stdout.strip().splitlines()
        processes = []
        for line in lines[1:]:
            parts = line.split(None, 3)
            if len(parts) == 4:
                pid, comm, cpu, mem = parts
                if filter_name and filter_name.lower() not in comm.lower():
                    continue
                processes.append({"pid": pid, "command": comm, "cpu_pct": cpu, "mem_pct": mem})
        return processes[:25]
