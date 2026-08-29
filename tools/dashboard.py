import json
import html
from pathlib import Path
from datetime import datetime


OUTCOME_COLORS = {
    "pr_created": "#22c55e",
    "pushed_no_pr": "#3b82f6",
    "dry_run_complete": "#a855f7",
    "aborted": "#eab308",
    "failed": "#ef4444",
    "in_progress": "#6b7280",
}


def _read_history(logs_dir: Path) -> list:
    history_file = logs_dir / "history.jsonl"
    if not history_file.exists():
        return []
    rows = []
    with open(history_file) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return list(reversed(rows))  # most recent first


def _row_html(row: dict) -> str:
    outcome = row.get("outcome", "unknown")
    color = OUTCOME_COLORS.get(outcome, "#6b7280")
    repo = html.escape(row.get("repository") or "—")
    issue = row.get("issue_number")
    issue_str = f"#{issue}" if issue else "—"
    dry = " (dry-run)" if row.get("dry_run") else ""
    started = row.get("started_at", "")
    prompt_tok = row.get("total_prompt_tokens", 0)
    completion_tok = row.get("total_completion_tokens", 0)
    calls = row.get("model_calls", 0)

    return f"""
    <tr>
      <td>{html.escape(started)}</td>
      <td>{repo}</td>
      <td>{issue_str}</td>
      <td><span class="badge" style="background:{color}">{html.escape(outcome)}{dry}</span></td>
      <td>{calls}</td>
      <td>{prompt_tok} in / {completion_tok} out</td>
    </tr>
    """


def generate_dashboard(logs_dir: Path, output_path: Path) -> Path:
    rows = _read_history(logs_dir)

    total_runs = len(rows)
    outcomes_count = {}
    total_prompt = 0
    total_completion = 0
    for r in rows:
        o = r.get("outcome", "unknown")
        outcomes_count[o] = outcomes_count.get(o, 0) + 1
        total_prompt += r.get("total_prompt_tokens", 0)
        total_completion += r.get("total_completion_tokens", 0)

    stat_cards = "".join(
        f'<div class="card"><div class="card-num">{count}</div><div class="card-label">{html.escape(name)}</div></div>'
        for name, count in outcomes_count.items()
    )

    rows_html = "".join(_row_html(r) for r in rows) or '<tr><td colspan="6">No runs yet.</td></tr>'

    generated_at = datetime.now().isoformat(timespec="seconds")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OSS Contribution Agent — Run Dashboard</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:2rem; }}
  h1 {{ font-size:1.5rem; margin-bottom:0.25rem; }}
  .subtitle {{ color:#94a3b8; margin-bottom:2rem; font-size:0.9rem; }}
  .stats {{ display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:2rem; }}
  .card {{ background:#1e293b; border-radius:10px; padding:1rem 1.5rem; min-width:120px; }}
  .card-num {{ font-size:1.8rem; font-weight:700; }}
  .card-label {{ color:#94a3b8; font-size:0.8rem; text-transform:capitalize; }}
  table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:10px; overflow:hidden; }}
  th, td {{ text-align:left; padding:0.75rem 1rem; font-size:0.85rem; border-bottom:1px solid #334155; }}
  th {{ background:#0f172a; color:#94a3b8; font-weight:600; text-transform:uppercase; font-size:0.7rem; letter-spacing:0.05em; }}
  .badge {{ padding:0.2rem 0.6rem; border-radius:6px; font-size:0.75rem; color:#0f172a; font-weight:600; }}
  footer {{ margin-top:2rem; color:#64748b; font-size:0.75rem; }}
</style>
</head>
<body>
  <h1>OSS Contribution Agent — Run Dashboard</h1>
  <div class="subtitle">{total_runs} total runs · {total_prompt} prompt tokens · {total_completion} completion tokens</div>

  <div class="stats">
    {stat_cards}
  </div>

  <table>
    <thead>
      <tr><th>Started</th><th>Repository</th><th>Issue</th><th>Outcome</th><th>Model Calls</th><th>Tokens</th></tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <footer>Generated {generated_at} · run <code>python tools/dashboard.py</code> to refresh</footer>
</body>
</html>"""

    output_path.write_text(page)
    return output_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config.settings import settings

    out = generate_dashboard(settings.LOGS_DIR, settings.LOGS_DIR / "dashboard.html")
    print(f"Dashboard written to: {out}")
