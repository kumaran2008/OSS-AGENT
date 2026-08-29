# Security Policy

## What this agent does with your credentials
- `GITHUB_TOKEN` and `OPENROUTER_API_KEY` are read from `.env` and never
  sent to any LLM prompt, logged to disk, or committed to git.
- Before running any shell command, both keys are stripped from the
  subprocess environment (see `tools/shell.py`), so a compromised or
  malicious repo cannot read them via `env` or similar.

## Known risk: test/lint execution is not sandboxed
This agent clones real, arbitrary GitHub repositories and runs their
test suite and linter via `subprocess` (e.g. `python -m pytest`,
`flake8 .`) directly on your device — there is **no container or VM
isolation** in this version.

This means:
- A malicious repository could include a test or setup file that
  executes arbitrary code on your machine when the test suite runs.
- Only run this agent against repositories you trust, or run it on a
  disposable device/environment (a spare VM, a throwaway cloud
  instance) if you plan to explore unfamiliar repositories.
- Containerized execution (Docker or similar) would close this gap
  but is intentionally out of scope for this version to keep the
  project dependency-light and runnable on Termux/mobile. Tracked as
  a future improvement — see ROADMAP.

## What is protected today
- All file operations are confined to the cloned repo's workspace
  folder — path traversal (`../`) is blocked (`tools/filesystem.py`).
- Shell commands are shown to you before execution and require
  manual confirmation unless `AUTO_APPROVE_COMMANDS=true` is set.
- A blocklist rejects known-dangerous command patterns (`rm -rf`,
  `sudo`, `curl | sh`, `.ssh` access, etc.) — this is a speed bump,
  **not a sandbox**, and should not be treated as a complete defense.
- The agent never auto-merges a pull request, and always requires
  explicit human approval before commit, push, or PR creation.

## Reporting a vulnerability
If you find a way to bypass the command blocklist, exfiltrate
secrets, or otherwise compromise the host running this agent, please
open a private security advisory on this repository (GitHub →
Security → Report a vulnerability) rather than a public issue.
