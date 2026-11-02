import os
import sys
import shutil
import platform
from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional


class DeviceTier(str, Enum):
    MOBILE = "mobile"                  # Low RAM, Termux/Android, no Docker, no CUDA
    MEDIUM_LAPTOP = "medium_laptop"    # 8-16GB RAM, standard Docker, CPU/low-end GPU
    HIGH_DESKTOP = "high_desktop"      # 32-64GB+ RAM, Metal/CUDA, fast local SLMs
    ENTERPRISE_SERVER = "server"       # 64GB+ RAM, Multi-GPU, MicroVM/KVM capable


@dataclass
class HardwareProfile:
    tier: DeviceTier
    total_ram_gb: float
    cpu_cores: int
    has_docker: bool
    has_cuda: bool
    has_metal: bool
    max_safe_workers: int
    default_sandbox_mode: str          # "bare_posix", "docker", "microvm", "remote_bridge"
    recommended_model_tier: str        # "cloud_only", "hybrid_small", "hybrid_medium", "local_heavy"


class PlatformAdapter:
    """
    Dynamically senses system hardware specifications and configures
    safe execution boundaries, worker concurrency, and sandboxing backends.
    """

    @classmethod
    def get_total_ram_gb(cls) -> float:
        """Determines physical RAM in GB using standard library and OS handles."""
        try:
            # Linux / Android / Termux
            if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
                pages = os.sysconf("SC_PHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                return round((pages * page_size) / (1024 ** 3), 2)
            # /proc/meminfo fallback
            meminfo = Path("/proc/meminfo")
            if meminfo.exists():
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        kb = int(parts[1])
                        return round(kb / (1024 ** 2), 2)
        except Exception:
            pass
        return 4.0

    @classmethod
    def detect_hardware(cls) -> HardwareProfile:
        total_ram = cls.get_total_ram_gb()
        cores = os.cpu_count() or 2
        is_android = (
            "com.termux" in os.environ.get("PREFIX", "")
            or "ANDROID_ROOT" in os.environ
            or "ANDROID_DATA" in os.environ
        )

        # Check Docker presence
        has_docker = (shutil.which("docker") is not None) and not is_android

        # Check CUDA availability
        has_cuda = False
        try:
            import subprocess
            res = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=1.0)
            has_cuda = (res.returncode == 0)
        except Exception:
            pass

        # Check Apple Silicon Metal
        has_metal = (platform.system() == "Darwin" and platform.machine() == "arm64")

        # Classify Tier
        if is_android or total_ram < 6.0:
            tier = DeviceTier.MOBILE
            workers = 1
            sandbox = "bare_posix"
            model_tier = "cloud_only"
        elif total_ram <= 18.0:
            tier = DeviceTier.MEDIUM_LAPTOP
            workers = 2
            sandbox = "docker" if has_docker else "bare_posix"
            model_tier = "hybrid_small"
        elif total_ram <= 64.0 and not (has_cuda and total_ram >= 64.0):
            tier = DeviceTier.HIGH_DESKTOP
            workers = max(4, cores // 2)
            sandbox = "docker" if has_docker else "bare_posix"
            model_tier = "hybrid_medium"
        else:
            tier = DeviceTier.ENTERPRISE_SERVER
            workers = max(8, cores - 2)
            sandbox = "microvm" if os.path.exists("/dev/kvm") else "docker"
            model_tier = "local_heavy"

        return HardwareProfile(
            tier=tier,
            total_ram_gb=total_ram,
            cpu_cores=cores,
            has_docker=has_docker,
            has_cuda=has_cuda,
            has_metal=has_metal,
            max_safe_workers=workers,
            default_sandbox_mode=sandbox,
            recommended_model_tier=model_tier
        )

    @classmethod
    def apply_runtime_guards(cls, profile: HardwareProfile):
        """Applies hardware-specific limits to process execution."""
        if profile.tier == DeviceTier.MOBILE:
            os.environ["OMP_NUM_THREADS"] = "2"
            os.environ["OPENBLAS_NUM_THREADS"] = "2"
            os.environ["MKL_NUM_THREADS"] = "2"
        elif profile.tier == DeviceTier.MEDIUM_LAPTOP:
            os.environ["OMP_NUM_THREADS"] = str(max(2, profile.cpu_cores // 2))
