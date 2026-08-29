⚠️ Security note: this agent runs a cloned repository's tests and linter directly on your device (no sandbox/container in this version). Only point it at repositories you trust. See SECURITY.md for details.
OSS Contribution Agent
An autonomous agent that discovers GitHub issues, understands a repository, drafts a fix using LLMs via OpenRouter, tests it, gets it reviewed by a separate model, and — only after your explicit approval at every stage — pushes a branch and opens a pull request.
It never auto-merges. It never pushes without asking. It never runs a shell command without showing it to you first.
Why this exists
Most AI coding agents (SWE-agent, OpenHands, Aider, Devin) assume a developer laptop or cloud sandbox. This one is built to run entirely inside Termux on an Android device — no Docker, no GPU, minimal dependencies — while keeping the same human-in-the-loop safety model a security-conscious engineer would want.
What it does
Searches GitHub for repositories (or targets one you name directly)
Finds an open issue worth attempting
Forks the repo into your account and clones the fork
Reads the README/docs/structure to build context
Asks an LLM to write an implementation plan
[Gate] asks you to approve the plan
Writes the code change
Runs the test suite; if it fails, a debugging LLM gets limited retries
Runs lint
Sends the diff to a separate reviewer LLM
[Gate] asks you to approve pushing
[Gate] asks you to approve opening the PR
Every LLM call is routed through a fallback chain (see Architecture) — if one model fails or gives unusable output, it automatically tries the next model configured for that task.


Setup

Termux (Android)
pkg update && pkg upgrade -y
pkg install python git -y
git clone <your-repo-url>
cd oss-agent
export ANDROID_API_LEVEL=24   # needed for pydantic-core to build
pip install -r requirements.txt
cp .env.example .env
nano .env   # fill in OPENROUTER_API_KEY and GITHUB_TOKEN



Mac / Linux / Windows (WSL)
git clone <your-repo-url>
cd oss-agent
pip install -r requirements.txt
cp .env.example .env
# edit .env with your keys


Getting your keys
OpenRouter API key — https://openrouter.ai/keys (also add credits at https://openrouter.ai/settings/credits — the agent will fail with a 402 error on any model call if your balance is $0)
GitHub token — use a classic token (Settings → Developer settings → Tokens (classic) → Generate new token (classic)) with the repo scope. Fine-grained tokens have been unreliable for fork creation in testing.

Usage
# Interactive: prompts for a search query
python main.py

# Target a specific repo directly, skip search
python main.py --repo psf/requests

# Search with a query
python main.py --query "language:python stars:>1000 good-first-issues:>5"

# Dry run: full pipeline, stops before any push/PR (safe for testing)
python main.py --dry-run --repo psf/requests


Configuration (.env)

OPENROUTER_API_KEY=...
GITHUB_TOKEN=...

# Single-model fallback (used if a task's chain below isn't set)
OPENROUTER_CODING_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_REVIEW_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_ANALYSIS_MODEL=openai/gpt-4o-mini

# Optional: per-task fallback chains (comma-separated, tried in order)
MODELS_PLANNING=anthropic/claude-3.5-sonnet,openai/gpt-4o
MODELS_CODING=anthropic/claude-3.5-sonnet,qwen/qwen-2.5-coder-32b-instruct
MODELS_REVIEW=openai/gpt-4o,anthropic/claude-3.5-sonnet
MODELS_DEBUG=deepseek/deepseek-coder,qwen/qwen-2.5-coder-32b-instruct
MODELS_ANALYSIS=openai/gpt-4o-mini,google/gemini-flash-1.5

AUTO_APPROVE_COMMANDS=false   # keep false unless you understand the risk
MAX_DEBUG_RETRIES=3
REPO_SELECTION_POOL_SIZE=5    # random pick from top N search results
WORKSPACE_DIR=./workspace
LOGS_DIR=./logs


Architecture

main.py
  → agent/orchestrator.py       (drives the whole pipeline + approval gates)
      → github/*.py             (repo search, issue search, forks, PRs)
      → llm/router.py           (per-task model fallback chains)
          → llm/openrouter.py   (raw OpenRouter API calls)
      → agent/coding_agent.py   (plan generation, patch generation)
      → agent/debugging_agent.py (fixes failing tests)
      → agent/reviewer_agent.py (independent review of the diff)
      → tools/*.py              (safe filesystem, shell, git, test runner)
      → tools/run_logger.py     (structured JSON log per run)

Full details in PROJECT-DOCUMENTATION.md.



Observability
Every run writes a structured log to logs/run-<id>.json and appends a summary line to logs/history.jsonl, including which model in each fallback chain actually succeeded and token usage per call.
Security
See SECURITY.md. In short: secrets are never sent to any LLM and are stripped from shell subprocess environments, but test/lint execution is not sandboxed — only run this against repositories you trust.
Contributing
See CONTRIBUTING.md.
Roadmap
Containerized/sandboxed test execution
CLI improvements (click, resuming a specific issue)
Web dashboard summarizing run history
Broader OpenRouter model catalog support


