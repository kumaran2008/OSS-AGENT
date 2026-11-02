#!/usr/bin/env bash
set -e
echo "[*] Initializing Sentinel-PC local environment..."
python3 -m venv .venv || true
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi
echo "[+] Environment initialized. Ensure Ollama (ollama run llama3.2) is running locally."
