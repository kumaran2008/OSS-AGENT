import os


class HardwareTier:
    TIER_LOW = "edge_low"      # Termux, phones, under 6GB RAM
    TIER_MID = "desktop_mid"   # Standard laptops, 8-16GB RAM
    TIER_HIGH = "server_high"  # Workstations, >16GB RAM, dedicated GPU


def detect_tier() -> str:
    # Termux / Android is always pinned to TIER_LOW for safety, regardless
    # of reported RAM — local model routing should never be attempted on
    # mobile even if the device technically has enough memory to try.
    if "com.termux" in os.environ.get("PREFIX", "") or "TERMUX_VERSION" in os.environ:
        return HardwareTier.TIER_LOW

    try:
        import psutil
        total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        # Fall back to the same cross-platform RAM detection used in
        # tools/system_info.py, rather than a hardcoded guess — reads
        # /proc/meminfo on Linux, sysctl on Mac, wmic on Windows.
        from tools.system_info import _read_ram_fallback
        total_ram_gb = _read_ram_fallback()

    if total_ram_gb < 6.0:
        return HardwareTier.TIER_LOW
    elif total_ram_gb <= 16.0:
        return HardwareTier.TIER_MID
    else:
        return HardwareTier.TIER_HIGH


CURRENT_TIER = detect_tier()
