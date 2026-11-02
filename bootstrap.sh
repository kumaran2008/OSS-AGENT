#!/usr/bin/env bash
set -euo pipefail

echo "================================================================="
echo "   OSS-AGENT: CROSS-PLATFORM SYSTEM BOOTSTRAPPER"
echo "================================================================="

OSS_DIR="$HOME/.oss_agent"
mkdir -p "$OSS_DIR/bin" "$OSS_DIR/models/slm" "$OSS_DIR/browser_profile"

OS="$(uname -s)"
ARCH="$(uname -m)"
echo "==> [1/4] Detected Host Environment: OS=$OS, ARCH=$ARCH"

if [ -d "/data/data/com.termux" ]; then
    echo "==> [Termux Environment Detected] Installing native dependencies..."
    pkg update -y
    pkg install -y python python-numpy clang libffi binutils ffmpeg termux-api
elif [ "$OS" = "Darwin" ]; then
    echo "==> [macOS Detected] Verifying Python runtime..."
elif [ "$OS" = "Linux" ]; then
    echo "==> [Linux Detected] Updating system packages..."
fi

echo "==> [2/4] Verifying Python Runtime..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required. Please install Python 3.10+."
    exit 1
fi

echo "==> [3/4] Scaffolding High-Performance Virtual Environment..."
if ! command -v uv &> /dev/null; then
    echo "Installing Astral UV package manager for isolated dependency resolution..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || true
    export PATH="$HOME/.cargo/bin:$PATH"
fi

if command -v uv &> /dev/null; then
    uv venv "$OSS_DIR/venv" --allow-existing
    # Activate virtual environment safely
    . "$OSS_DIR/venv/bin/activate" || true
    uv pip install --upgrade edge-tts
else
    python3 -m pip install --upgrade edge-tts
fi

echo "==> [4/4] System Operational. Launching Engine Diagnostic..."
python3 -c "from agent.pa_scaffolder.platform_detector import HARDWARE_PROFILE; print(f'Hardware Profile: {HARDWARE_PROFILE.os.value} on {HARDWARE_PROFILE.arch}')"

echo "================================================================="
echo ">>> BOOTSTRAP COMPLETE: SYSTEM READY FOR ACTIVE EXECUTION <<<"
echo "================================================================="
