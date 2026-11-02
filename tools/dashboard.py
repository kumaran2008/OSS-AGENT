import os
import sys
import json
import html
import threading
import http.server
import socketserver
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.system_info import get_system_capabilities as get_system_info
from llm.router import HardwareSpecDetector, ModelRouter

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
    return list(reversed(rows))

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
    return f"""<tr>
      <td>{html.escape(started)}</td>
      <td>{repo}</td>
      <td>{issue_str}</td>
      <td><span style="background:{color}; padding: 2px 6px; border-radius: 4px;">{html.escape(outcome)}{dry}</span></td>
      <td>{calls}</td>
      <td>{prompt_tok} in / {completion_tok} out</td>
    </tr>"""

def generate_dashboard(logs_dir: Path, output_path: Path) -> Path:
    rows = _read_history(logs_dir)
    total_runs = len(rows)
    total_prompt = sum(r.get("total_prompt_tokens", 0) for r in rows)
    total_completion = sum(r.get("total_completion_tokens", 0) for r in rows)
    rows_html = "".join(_row_html(r) for r in rows) or '<tr><td colspan="6">No runs yet.</td></tr>'
    
    page = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>OSS-Agent Runs</title></head>
<body style="background:#0d1117; color:#f0f6fc; font-family:sans-serif; padding:2rem;">
  <h2>Run History ({total_runs} runs, {total_prompt + total_completion} tokens)</h2>
  <table border="1" cellpadding="8" style="border-collapse:collapse; width:100%; border-color:#30363d;">
    <thead><tr><th>Started</th><th>Repository</th><th>Issue</th><th>Outcome</th><th>Calls</th><th>Tokens</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</body></html>"""
    output_path.write_text(page)
    return output_path

_EVENT_HISTORY: List[Dict[str, Any]] = []
_SYSTEM_SPECS = get_system_info()
_LAST_LOG_MESSAGE = ""
_SHARED_ROUTER: Optional[ModelRouter] = None

# Global Human-in-the-loop Approval Registry
_PENDING_APPROVAL: Optional[Dict[str, Any]] = None
_APPROVAL_EVENT = threading.Event()
_APPROVAL_DECISION: bool = False


def get_shared_router() -> ModelRouter:
    global _SHARED_ROUTER
    if _SHARED_ROUTER is None:
        from config.settings import settings
        chains = settings.get_task_chains() if hasattr(settings, "get_task_chains") else getattr(settings, "TASK_CHAINS", {})
        _SHARED_ROUTER = ModelRouter(task_chains=chains)
    return _SHARED_ROUTER


def request_human_approval(title: str, description: str, diff: str = "", metadata: Dict[str, Any] = None) -> bool:
    """
    Blocks backend execution until approved via Web Dashboard UI or CLI fallback.
    """
    global _PENDING_APPROVAL, _APPROVAL_EVENT, _APPROVAL_DECISION
    _APPROVAL_EVENT.clear()
    _APPROVAL_DECISION = False

    _PENDING_APPROVAL = {
        "id": f"appr_{int(datetime.now().timestamp())}",
        "title": title,
        "description": description,
        "diff": diff,
        "metadata": metadata or {},
        "created_at": datetime.now().isoformat()
    }

    dashboard.emit("AWAITING_APPROVAL", _PENDING_APPROVAL)
    print(f"\n[HUMAN APPROVAL REQUIRED] {title}: {description}")
    print("Waiting for browser action at http://localhost:8000 ...")

    # Wait up to 10 minutes for web approval before falling back
    approved = _APPROVAL_EVENT.wait(timeout=600)
    decision = _APPROVAL_DECISION if approved else False
    _PENDING_APPROVAL = None

    dashboard.emit("APPROVAL_RESOLVED", {"approved": decision})
    return decision


class DashboardHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):

    def translate_path(self, path: str) -> str:
        if path in ("/", "/index.html"):
            template_path = Path(__file__).parent / "templates" / "index.html"
            if template_path.exists():
                return str(template_path)
        return super().translate_path(path)

    def _set_json_headers(self, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_json_headers(200)

    def do_GET(self):
        if self.path == "/api/specs":
            self._set_json_headers(200)
            specs = dict(_SYSTEM_SPECS)
            specs["tier"] = HardwareSpecDetector.detect_tier()
            specs["ram_gb"] = HardwareSpecDetector.get_system_ram_gb()
            self.wfile.write(json.dumps(specs).encode("utf-8"))
            return

        if self.path == "/api/models":
            self._set_json_headers(200)
            router = get_shared_router()
            balance = router.get_account_balance()
            tier = router.hardware_tier
            ollama_online = router.local_client.is_available()

            data = {
                "tier": tier,
                "ram_gb": HardwareSpecDetector.get_system_ram_gb(),
                "openrouter_balance_usd": balance,
                "ollama_available": ollama_online,
                "mode": router.mode
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if self.path == "/api/events":
            self._set_json_headers(200)
            self.wfile.write(json.dumps(_EVENT_HISTORY[-60:]).encode("utf-8"))
            return

        if self.path == "/api/approval":
            self._set_json_headers(200)
            self.wfile.write(json.dumps({"pending": _PENDING_APPROVAL}).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        global _APPROVAL_DECISION
        if self.path == "/api/ollama/pull":
            content_length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            model_name = payload.get("model", "").strip()

            if not model_name:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({"error": "No model specified"}).encode("utf-8"))
                return

            def _pull_worker():
                dashboard.emit("STATE_CHANGE", {"state": "WORKING"})
                dashboard.emit("LOG_STREAM", {"message": f"Pulling model: {model_name} via Ollama..."})
                import subprocess
                try:
                    res = subprocess.run(["ollama", "pull", model_name], capture_output=True, text=True)
                    if res.returncode == 0:
                        dashboard.emit("LOG_STREAM", {"message": f"Successfully installed {model_name}"})
                        dashboard.emit("STATE_CHANGE", {"state": "SUCCESS"})
                    else:
                        dashboard.emit("LOG_STREAM", {"message": f"Ollama pull failed: {res.stderr[:80]}"})
                        dashboard.emit("STATE_CHANGE", {"state": "ERROR"})
                except Exception as ex:
                    dashboard.emit("LOG_STREAM", {"message": f"Ollama pull error: {str(ex)}"})
                    dashboard.emit("STATE_CHANGE", {"state": "ERROR"})

            threading.Thread(target=_pull_worker, daemon=True).start()
            self._set_json_headers(200)
            self.wfile.write(json.dumps({"status": "pull_started", "model": model_name}).encode("utf-8"))
            return

        if self.path == "/api/approval":
            content_length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            decision = bool(payload.get("approved", False))
            _APPROVAL_DECISION = decision
            _APPROVAL_EVENT.set()
            self._set_json_headers(200)
            self.wfile.write(json.dumps({"status": "resolved", "decision": decision}).encode("utf-8"))
            return

        if self.path == "/api/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            prompt = payload.get("prompt", "").strip()

            if not prompt:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({"error": "Empty prompt"}).encode("utf-8"))
                return

            dashboard.emit("STATE_CHANGE", {"state": "THINKING"})
            dashboard.emit("AGENT_ACTIVE", {"name": "SUPERVISOR", "role": "Orchestrator", "status": "Deconstructing task"})
            dashboard.emit("LOG_STREAM", {"message": f"Supervisor planning: '{prompt[:45]}...'"})

            router = get_shared_router()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the Parent Supervisor of OSS-Agent, an adaptive, local-first engineering workstation. "
                        "Respond cleanly and concisely in structured markdown. For software build requests, present "
                        "explicit architectural specs and work breakdowns."
                    )
                },
                {"role": "user", "content": prompt}
            ]

            try:
                reply, model_used = router.complete_with_fallback("orchestration", messages)
                dashboard.emit("STATE_CHANGE", {"state": "SUCCESS"})
                dashboard.emit("LOG_STREAM", {"message": f"Resolved via [{model_used}]"})
                dashboard.emit("AGENT_INACTIVE", {"name": "SUPERVISOR"})

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    "response": reply,
                    "model_used": model_used,
                    "status": "success"
                }).encode("utf-8"))
            except Exception as e:
                dashboard.emit("STATE_CHANGE", {"state": "ERROR"})
                dashboard.emit("LOG_STREAM", {"message": f"Pipeline failure: {str(e)}"})
                self._set_json_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        self._set_json_headers(404)
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def log_message(self, format, *args):
        pass


class GlassBoxDashboardServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        def run_server():
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer((self.host, self.port), DashboardHTTPRequestHandler) as httpd:
                self.server = httpd
                httpd.serve_forever()

        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        print(f"[GlassBox Dashboard] Live workstation running at http://localhost:{self.port}")

    def emit(self, event_type: str, data: Dict[str, Any]):
        global _LAST_LOG_MESSAGE
        if event_type == "LOG_STREAM":
            msg = data.get("message", "").strip()
            if msg == _LAST_LOG_MESSAGE:
                return
            _LAST_LOG_MESSAGE = msg

        payload = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        _EVENT_HISTORY.append(payload)
        if len(_EVENT_HISTORY) > 100:
            _EVENT_HISTORY.pop(0)


dashboard = GlassBoxDashboardServer()
