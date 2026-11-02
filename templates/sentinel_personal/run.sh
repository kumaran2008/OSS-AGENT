#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOCAL_LLM_URL="${LOCAL_LLM_URL:-http://localhost:11434/v1/chat/completions}"
export LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-llama3.2}"
python3 "${SCRIPT_DIR}/cli.py" "$@"
