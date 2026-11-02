#!/usr/bin/env bash
set -e

echo "============================================================"
echo "    AEGIS :: AUTONOMOUS COMPANION & AGENT INSTALLER"
echo "============================================================"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# 1. Environment Detection
IS_TERMUX=false
if [ -d "/data/data/com.termux" ] || [ -n "$TERMUX_VERSION" ]; then
    IS_TERMUX=true
    echo "[*] Target Environment: Android / Termux"
else
    echo "[*] Target Environment: $(uname -s) / $(uname -m)"
fi

# 2. Python Check
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is required. Please install python3 first."
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[+] Python $PY_VER detected."

# 3. Install Core Dependencies
echo "[*] Ensuring essential packages are present..."
PIP_FLAGS=""
if [ "$IS_TERMUX" = true ]; then
    PIP_FLAGS="--break-system-packages"
fi

python3 -m pip install requests click pydantic python-dotenv $PIP_FLAGS > /dev/null 2>&1 || true

# 4. Configure Persistent Shell Command Aliases
PA_BIN="$HOME/.personal_agent/pa"
SHELL_RC=""
if [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
fi

if [ -n "$SHELL_RC" ]; then
    # Register 'pa' alias
    if ! grep -q "alias pa=" "$SHELL_RC"; then
        echo "alias pa='python3 \$HOME/.personal_agent/runtime/pa_runtime.py'" >> "$SHELL_RC"
        echo "[+] Added 'pa' command alias to $SHELL_RC"
    fi
    # Register 'oss-agent' alias
    if ! grep -q "alias oss-agent=" "$SHELL_RC"; then
        echo "alias oss-agent='python3 $REPO_DIR/main.py'" >> "$SHELL_RC"
        echo "[+] Added 'oss-agent' command alias to $SHELL_RC"
    fi
fi

# 5. Initialize Personal Agent Scaffolding
echo ""
echo "[*] Provisioning default Personal Agent companion..."
python3 -c "
from pathlib import Path
from agent.pa_scaffolder import PersonalAgentConfig, AgentPersona, OperatorProfile, PersonalAgentScaffolder
scaffolder = PersonalAgentScaffolder()
if not (Path.home() / '.personal_agent' / 'config.json').exists():
    cfg = PersonalAgentConfig(
        persona=AgentPersona(name='Hype', tone_style='Supportive & High Energy'),
        operator=OperatorProfile(call_sign='Operator')
    )
    scaffolder.deploy(cfg)
    print('[+] Companion successfully initialized at ~/.personal_agent/')
else:
    print('[+] Existing companion configuration detected at ~/.personal_agent/')
"

echo ""
echo "============================================================"
echo " [✓] INSTALLATION COMPLETE"
echo "============================================================"
echo " • Run 'pa' anywhere to chat with your companion."
echo " • Run 'python3 main.py --server-only' to launch the streaming UI."
echo "============================================================"
