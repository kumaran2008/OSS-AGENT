import os
import platform
import shutil
import subprocess
import sys
from typing import Dict, Any

try:
    import psutil
except ImportError:
    psutil = None


def _read_ram_fallback() -> float:
    """
    Fallback RAM detection for platforms where psutil isn't available
    or fails to install (notably Android/Termux, where psutil's wheel
    build is explicitly unsupported). Tries the best method per OS
    before giving up to a conservative default.
    """
    system = platform.system().lower()

    # Linux and Android/Termux both expose /proc/meminfo — same read works for both.
    if system == "linux" or "TERMUX_VERSION" in os.environ:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 2)
        except Exception:
            pass

    # macOS (Intel and Apple Silicon) — sysctl reports total physical RAM in bytes.
    if system == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                total_bytes = int(result.stdout.strip())
                return round(total_bytes / (1024 ** 3), 2)
        except Exception:
            pass

    # Windows — wmic reports total physical memory in bytes.
    if system == "windows":
        try:
            result = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    return round(int(line) / (1024 ** 3), 2)
        except Exception:
            pass

    return 4.0  # conservative fallback if every platform-specific method fails


def _detect_gpu() -> bool:
    """Best-effort GPU presence check — not exhaustive, but catches the
    common cases (NVIDIA via nvidia-smi, Apple Silicon which always has
    a usable GPU for Metal-accelerated inference)."""
    if platform.system().lower() == "darwin" and platform.machine() == "arm64":
        return True  # Apple Silicon always has a usable GPU
    if shutil.which("nvidia-smi") is not None:
        return True
    return False


def get_system_capabilities() -> Dict[str, Any]:
    """
    Detects operating system, environment type (Termux/Windows/Mac/Linux),
    available hardware resources (CPU cores, RAM, GPU), and local model
    readiness.
    """
    is_termux = "TERMUX_VERSION" in os.environ or "/data/data/com.termux" in sys.prefix
    os_name = platform.system().lower()

    if psutil:
        try:
            ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
        except Exception:
            ram_gb = _read_ram_fallback()
    else:
        ram_gb = _read_ram_fallback()

    cpu_count = os.cpu_count() or 2
    ollama_installed = shutil.which("ollama") is not None
    has_gpu = _detect_gpu()

    return {
        "is_termux": is_termux,
        "os": os_name,
        "ram_gb": ram_gb,
        "cpu_count": cpu_count,
        "ollama_installed": ollama_installed,
        "has_gpu": has_gpu,
        # 8GB+ is the minimum to attempt local inference at all; 16GB+ or
        # a GPU is where it's actually comfortable, not just possible.
        "can_run_local_llama": (ram_gb >= 8.0 and not is_termux),
        "local_llama_recommended": (ram_gb >= 16.0 or has_gpu) and not is_termux,
    }


def print_ollama_setup_guide() -> None:
    """Prints clear CLI setup instructions for running Llama locally via Ollama."""
    print("\n" + "=" * 60)
    print("        LOCAL LLAMA / OLLAMA SETUP GUIDE")
    print("=" * 60)
    print("1. Download & Install Ollama:")
    print("   • macOS / Windows: Download from https://ollama.com/download")
    print("   • Linux: Run -> curl -fsSL https://ollama.com/install.sh | sh")
    print("\n2. Pull a local coding model:")
    print("   • Run -> ollama pull qwen2.5-coder:7b   (Recommended for 8GB-16GB RAM)")
    print("   • Run -> ollama pull llama3.3           (Recommended for 32GB+ RAM)")
    print("\n3. Start Ollama engine:")
    print("   • Run -> ollama serve")
    print("=" * 60 + "\n")


def select_execution_mode() -> str:
    """Interactively prompts the user to select Local Llama vs Cloud execution."""
    specs = get_system_capabilities()

    env_str = "Termux (Android)" if specs["is_termux"] else specs["os"].upper()
    gpu_str = ", GPU detected" if specs["has_gpu"] else ""
    print(f"\n[System Sensor] Detected OS: {env_str} | RAM: {specs['ram_gb']} GB | "
          f"CPU Cores: {specs['cpu_count']}{gpu_str}")

    if specs["can_run_local_llama"]:
        confidence = "High-capacity hardware detected!" if specs["local_llama_recommended"] \
            else "Local inference is possible here, but may run slowly (8-16GB RAM, no GPU detected)."
        print(f"\n[?] {confidence}")
        print("    (1) Local Llama / Ollama Mode (100% Offline & Free)")
        print("    (2) OpenRouter Cloud Routing")

        choice = input("\nSelect Mode (1/2) [Default=2]: ").strip()
        if choice == "1":
            if not specs["ollama_installed"]:
                print_ollama_setup_guide()
                print("Take your time — install Ollama and pull a model in another terminal.")
                while True:
                    ready = input(
                        "\nType 'r' to re-check once installed, or 'c' to fall back to Cloud Mode: "
                    ).strip().lower()
                    if ready == "c":
                        print("[Info] Falling back to OpenRouter Cloud Mode...")
                        return "openrouter"
                    if ready == "r":
                        if shutil.which("ollama") is not None:
                            print("[Info] Ollama detected! Continuing in Local Llama mode.")
                            break
                        print("[Info] Ollama still not found on PATH. Make sure it's installed and try again.")
            return "local_llama"

    print("[Info] Initializing in Cloud Mode (OpenRouter)...")
    return "openrouter"


if __name__ == "__main__":
    # Test script standalone
    mode = select_execution_mode()
    print(f"[Selected Execution Mode]: {mode}")
