# Contributing

Thanks for considering contributing to OSS Contribution Agent.

## Before you start
- Read `SECURITY.md` — this project executes code from arbitrary
  repositories, and any change touching `tools/shell.py`,
  `tools/filesystem.py`, or `tools/git.py` needs extra scrutiny.
- Never weaken the human-approval gates in `agent/orchestrator.py`
  (issue selection, implementation, push, PR creation) without
  discussion first — they are a deliberate safety design, not
  leftover scaffolding.

## Setup
See `README.md` for environment setup (Termux/Linux/Mac/Windows-WSL).

## Development workflow
1. Make your change.
2. Test with `python main.py --dry-run --repo <owner/name>` first —
   this exercises the full pipeline without pushing or opening a PR.
3. Run against a real low-stakes repo only after the dry run looks
   correct.
4. Commit with a clear message describing the change and why.

## Code style
- Keep modules single-purpose (see the existing `agent/`, `tools/`,
  `github/`, `llm/` separation) — new functionality should extend an
  existing module or get its own, not get bolted onto an unrelated one.
- Any new dangerous shell pattern should be added to
  `DANGEROUS_PATTERNS` in `tools/shell.py`, with a comment explaining
  the risk it blocks.

## Reporting bugs
Open an issue with the command you ran, the full traceback, and
(if relevant) which repo/issue triggered it. Never include your
`.env` contents, tokens, or API keys in a bug report.
