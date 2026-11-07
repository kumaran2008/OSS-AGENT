from __future__ import annotations
import ast
import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from agent.guardrails.prm_verifier import ProcessRewardGuard
from agent.kernel.sandbox_isolation import subprocess_sandbox


@dataclass
class OrynxActionItem:
    action_type: str  # 'file' | 'shell' | 'start' | 'build' | 'supabase' | 'patch'
    file_path: Optional[str] = None
    content: str = ""
    status: str = "PENDING"
    execution_ms: float = 0.0
    error_detail: Optional[str] = None
    sha256_after: Optional[str] = None


@dataclass
class StreamingParserState:
    buffer: str = ""
    current_artifact_id: Optional[str] = None
    current_artifact_title: Optional[str] = None
    in_artifact: bool = False
    in_action: bool = False
    current_action_type: Optional[str] = None
    current_file_path: Optional[str] = None
    completed_actions: List[OrynxActionItem] = field(default_factory=list)
    chunks_fed: int = 0


class IncrementalErrorMemoryBox:
    """
    Transient SQLite Error Memory Box (`transient_error_ledger`).
    Records syntax, import, typecheck, and runtime faults across progressive
    multi-file add-ons at $0.00 LLM cost, then flushes compact AST slices in batch.
    """

    def __init__(self, db_path: str = "workspace/kernel_governance.db", flush_threshold: int = 3):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.flush_threshold = flush_threshold
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_error_memory_box (
                    error_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    file_path TEXT,
                    symbol_name TEXT,
                    line_no INTEGER,
                    error_type TEXT,
                    error_message TEXT,
                    ast_slice TEXT,
                    resolved INTEGER DEFAULT 0,
                    created_at REAL
                )
                """
            )

    def extract_ast_fault_context(self, source_code: str, error_lineno: int = 1) -> Dict[str, Any]:
        lines = source_code.splitlines()
        start_idx = max(0, error_lineno - 4)
        end_idx = min(len(lines), error_lineno + 4)
        snippet = "\n".join(f"{i+1}: {lines[i]}" for i in range(start_idx, end_idx))
        symbol = "<module>"
        for i in range(min(len(lines) - 1, error_lineno - 1), -1, -1):
            stripped = lines[i].strip()
            if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class "):
                symbol = stripped.split("(")[0].split(":")[0]
                break
        return {"symbol_name": symbol, "ast_slice": snippet}

    def record_error(
        self,
        session_id: str,
        file_path: str,
        error_type: str,
        error_message: str,
        line_no: int = 1,
        symbol_name: str = "<module>",
        ast_slice: str = "",
        source_code: str = "",
    ) -> Dict[str, Any]:
        if source_code and not ast_slice:
            extracted = self.extract_ast_fault_context(source_code, error_lineno=line_no)
            symbol_name = extracted["symbol_name"]
            ast_slice = extracted["ast_slice"]

        err_id = f"err_{int(time.time() * 1000)}_{abs(hash((file_path, line_no, error_message))) % 100000}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orynx_error_memory_box
                (error_id, session_id, file_path, symbol_name, line_no, error_type, error_message, ast_slice, resolved, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (err_id, session_id, file_path, symbol_name, int(line_no), error_type, error_message, ast_slice, time.time()),
            )
            unresolved_count = conn.execute(
                "SELECT COUNT(*) FROM orynx_error_memory_box WHERE session_id = ? AND resolved = 0",
                (session_id,),
            ).fetchone()[0]

        return {
            "error_id": err_id,
            "session_id": session_id,
            "file_path": file_path,
            "symbol_name": symbol_name,
            "line_no": line_no,
            "error_type": error_type,
            "unresolved_count": unresolved_count,
            "threshold_reached": unresolved_count >= self.flush_threshold,
            "llm_tokens_spent": 0,
        }

    def get_unresolved_errors(self, session_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT error_id, file_path, symbol_name, line_no, error_type, error_message, ast_slice
                FROM orynx_error_memory_box
                WHERE session_id = ? AND resolved = 0
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "error_id": r[0],
                "file_path": r[1],
                "symbol_name": r[2],
                "line_no": r[3],
                "error_type": r[4],
                "error_message": r[5],
                "ast_slice": r[6],
            }
            for r in rows
        ]

    def build_compact_repair_prompt(self, session_id: str) -> Dict[str, Any]:
        pending = self.get_unresolved_errors(session_id)
        blocks: List[str] = []
        for item in pending:
            blocks.append(
                f"[{item['error_type']}] {item['file_path']}:{item['line_no']} in {item['symbol_name']}\n"
                f"Msg: {item['error_message']}\nSlice:\n{item['ast_slice']}"
            )
        compact_prompt = "\n---\n".join(blocks)
        return {
            "session_id": session_id,
            "error_count": len(pending),
            "estimated_tokens": max(1, len(compact_prompt) // 4),
            "compact_repair_payload": compact_prompt,
        }

    def flush_and_mark_resolved(self, session_id: str) -> Dict[str, Any]:
        pending = self.get_unresolved_errors(session_id)
        repair_bundle = self.build_compact_repair_prompt(session_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE orynx_error_memory_box SET resolved = 1 WHERE session_id = ? AND resolved = 0",
                (session_id,),
            )
        return {
            "session_id": session_id,
            "flushed_error_count": len(pending),
            "repair_bundle_tokens": repair_bundle["estimated_tokens"],
            "errors_resolved": pending,
        }


class OrynxArtifactStreamRunner:
    """
    Full Streaming Artifact & Action State Machine ported and upgraded from bolt.diy:
    - Handles both complete streams and incremental chunk-by-chunk streaming (`feed_chunk`)
    - Supports surgical SEARCH/REPLACE diff blocks so 800-line files don't need full rewrites
    - Verifies AST via ProcessRewardGuard and links multi-file add-ons in the warm sandbox
    """

    ARTIFACT_RE = re.compile(
        r"<(?:orynx|bolt)Artifact[^>]*id=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*title=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*>(.*?)</(?:orynx|bolt)Artifact>",
        re.DOTALL,
    )
    ACTION_RE = re.compile(
        r"<(?:orynx|bolt)Action[^>]*type=[\x22\x27]([^\x22\x27]+)[\x22\x27](?:\s+filePath=[\x22\x27]([^\x22\x27]+)[\x22\x27])?[^>]*>(.*?)</(?:orynx|bolt)Action>",
        re.DOTALL,
    )
    SEARCH_REPLACE_RE = re.compile(
        r"<<<< SEARCH\n(.*?)\n====\n(.*?)\n>>>> REPLACE",
        re.DOTALL,
    )

    def __init__(self, error_box: Optional[IncrementalErrorMemoryBox] = None):
        self.error_box = error_box or IncrementalErrorMemoryBox()
        self._stream_states: Dict[str, StreamingParserState] = {}

    def feed_chunk(self, session_id: str, token_chunk: str) -> Dict[str, Any]:
        """
        Real-time incremental token chunk state machine (mirrors bolt.diy StreamingMessageParser).
        Safely buffers partial tags across chunk boundaries and emits actions as soon as </orynxAction> closes.
        """
        state = self._stream_states.setdefault(session_id, StreamingParserState())
        state.buffer += token_chunk
        state.chunks_fed += 1
        newly_completed: List[OrynxActionItem] = []

        if not state.in_artifact:
            art_open = re.search(
                r"<(?:orynx|bolt)Artifact[^>]*id=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*title=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*>",
                state.buffer,
            )
            if art_open:
                state.in_artifact = True
                state.current_artifact_id = art_open.group(1)
                state.current_artifact_title = art_open.group(2)
                state.buffer = state.buffer[art_open.end():]

        while True:
            act_match = self.ACTION_RE.search(state.buffer)
            if not act_match:
                break
            a_type = act_match.group(1).strip()
            f_path = act_match.group(2).strip() if act_match.group(2) else None
            body = act_match.group(3).strip()
            item = OrynxActionItem(action_type=a_type, file_path=f_path, content=body, status="PARSED_FROM_STREAM")
            state.completed_actions.append(item)
            newly_completed.append(item)
            state.buffer = state.buffer[act_match.end():]

        if "</orynxArtifact>" in state.buffer or "</boltArtifact>" in state.buffer:
            state.in_artifact = False

        return {
            "session_id": session_id,
            "chunks_fed": state.chunks_fed,
            "artifact_id": state.current_artifact_id,
            "newly_completed_actions": len(newly_completed),
            "total_completed_actions": len(state.completed_actions),
        }

    def apply_surgical_search_replace(self, existing_text: str, patch_body: str) -> Tuple[str, int]:
        """Applies one or more <<<< SEARCH / ==== / >>>> REPLACE blocks without rewriting the whole file."""
        updated = existing_text
        applied_count = 0
        for m in self.SEARCH_REPLACE_RE.finditer(patch_body):
            search_block = m.group(1)
            replace_block = m.group(2)
            if search_block in updated:
                updated = updated.replace(search_block, replace_block, 1)
                applied_count += 1
        return updated, applied_count

    def parse_artifact_stream(self, raw_stream: str) -> Dict[str, Any]:
        artifacts: List[Dict[str, Any]] = []
        for art_match in self.ARTIFACT_RE.finditer(raw_stream):
            art_id, art_title, inner = art_match.group(1), art_match.group(2), art_match.group(3)
            actions: List[OrynxActionItem] = []
            for act_match in self.ACTION_RE.finditer(inner):
                a_type = act_match.group(1).strip()
                f_path = act_match.group(2).strip() if act_match.group(2) else None
                body = act_match.group(3).strip()
                actions.append(OrynxActionItem(action_type=a_type, file_path=f_path, content=body))
            artifacts.append({"id": art_id, "title": art_title, "actions": actions})
        return {"artifact_count": len(artifacts), "artifacts": artifacts}

    def execute_artifact_actions(
        self,
        project_dir: Path,
        raw_stream: str,
        session_id: str = "orynx_default_session",
    ) -> Dict[str, Any]:
        project_dir.mkdir(parents=True, exist_ok=True)
        parsed = self.parse_artifact_stream(raw_stream)
        written_files: List[str] = []
        executed_commands: List[Dict[str, Any]] = []
        logged_errors: List[Dict[str, Any]] = []

        for art in parsed["artifacts"]:
            for action in art["actions"]:
                t0 = time.perf_counter()
                if action.action_type in ("file", "patch") and action.file_path:
                    target_file = (project_dir / action.file_path).resolve()
                    if not str(target_file).startswith(str(project_dir.resolve())):
                        err = self.error_box.record_error(
                            session_id, action.file_path, "PathTraversalBlocked", "Blocked path outside project root"
                        )
                        logged_errors.append(err)
                        action.status = "BLOCKED"
                        continue

                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    final_content = action.content
                    if "<<<< SEARCH" in action.content and target_file.exists():
                        existing_src = target_file.read_text(encoding="utf-8", errors="ignore")
                        final_content, _ = self.apply_surgical_search_replace(existing_src, action.content)

                    if target_file.suffix == ".py":
                        prm = ProcessRewardGuard.verify_python_syntax(final_content)
                        if not prm.is_valid:
                            lineno = 1
                            m_line = re.search(r"line (\d+)", prm.error_message or "")
                            if m_line:
                                lineno = int(m_line.group(1))
                            err = self.error_box.record_error(
                                session_id=session_id,
                                file_path=action.file_path,
                                error_type="SyntaxError",
                                error_message=prm.error_message or "Invalid Python syntax",
                                line_no=lineno,
                                source_code=final_content,
                            )
                            logged_errors.append(err)
                            action.status = "LOGGED_TO_ERROR_BOX"
                            continue

                    target_file.write_text(final_content + "\n", encoding="utf-8")
                    action.sha256_after = hashlib.sha256(final_content.encode("utf-8")).hexdigest()
                    written_files.append(action.file_path)
                    action.status = "COMPLETED"
                    action.execution_ms = round((time.perf_counter() - t0) * 1000.0, 2)

                elif action.action_type in ("shell", "start", "build"):
                    cmd_str = action.content.strip()
                    if cmd_str.startswith("npm install"):
                        cmd_str = cmd_str.replace("npm install", "pnpm install --prefer-offline", 1)
                    if cmd_str.startswith("python"):
                        parts = cmd_str.split()
                        sb_res = subprocess_sandbox.execute_sandboxed(parts, cwd=str(project_dir), timeout_s=10.0)
                        if sb_res["exit_code"] != 0:
                            err = self.error_box.record_error(
                                session_id=session_id,
                                file_path=parts[-1] if len(parts) > 1 else "shell",
                                error_type="RuntimeExecutionError",
                                error_message=sb_res["stderr"][:300],
                            )
                            logged_errors.append(err)
                            action.status = "LOGGED_TO_ERROR_BOX"
                        else:
                            action.status = "COMPLETED"
                        executed_commands.append({
                            "command": cmd_str,
                            "exit_code": sb_res["exit_code"],
                            "stdout": sb_res["stdout"][:300],
                        })
                    else:
                        action.status = "STAGED_COMMAND"
                        executed_commands.append({"command": cmd_str, "exit_code": 0, "stdout": "Staged in container runner"})
                    action.execution_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return {
            "session_id": session_id,
            "artifacts_processed": parsed["artifact_count"],
            "written_files": written_files,
            "executed_commands": executed_commands,
            "errors_logged_to_box": logged_errors,
            "unresolved_error_count": len(self.error_box.get_unresolved_errors(session_id)),
        }
