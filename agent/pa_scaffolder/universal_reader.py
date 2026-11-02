from __future__ import annotations

import hashlib
import html
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.pa_scaffolder.blackboard_kernel import undo_ledger
from agent.pa_scaffolder.kernel_governance import enforce_owner_only_permissions

try:
    from tools.desktop import desktop_controller
except Exception:
    desktop_controller = None


class UniversalReader:
    """Universal Sensory Ingestion, Persistent Book/PDF Bookmark Tracker & Two-Way Messaging Bridge."""

    DB_PATH = Path("workspace/kernel_governance.db")

    def __init__(self):
        self.workspace = Path("workspace")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.transcript_dir = self.workspace / "media_transcripts"
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_path = self.workspace / "outbound_messages.jsonl"
        self._seen_notification_ids: set[str] = set()
        self._live_notification_queue: List[Dict[str, Any]] = []
        self._last_clipboard_hash: str = ""
        self._init_bookmark_db()

    def _init_bookmark_db(self) -> None:
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reading_bookmarks (
                    file_key TEXT PRIMARY KEY,
                    canonical_path TEXT NOT NULL,
                    last_start_line INTEGER NOT NULL,
                    last_end_line INTEGER NOT NULL,
                    total_lines INTEGER NOT NULL,
                    updated_at REAL
                )
                """
            )
            conn.commit()
        enforce_owner_only_permissions(self.DB_PATH)

    # -------------------------------------------------------------------------
    # 1. Screen OCR
    # -------------------------------------------------------------------------
    def read_screen(self, region_hint: str = "full") -> str:
        from agent.pa_scaffolder.vision_analyzer import vision_analyzer
        scr_path = vision_analyzer.capture_live_screen()
        ocr_text, ui_boxes = vision_analyzer.extract_ui_elements_and_ocr(scr_path)
        if ocr_text.strip():
            return ocr_text.strip()
        meta = vision_analyzer.read_png_visual_meta(scr_path)
        if meta and meta.get("ocr_text"):
            return meta["ocr_text"]
        return f"Screen captured ({scr_path.name}) with {len(ui_boxes)} UI regions."

    # -------------------------------------------------------------------------
    # 2. Full YouTube Timestamped Transcript Extractor
    # -------------------------------------------------------------------------
    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([a-zA-Z0-9_\-]{6,15})", url)
        return m.group(1) if m else None

    @staticmethod
    def _format_ts(seconds: float) -> str:
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"[{m:02d}:{s:02d}]"

    def register_local_transcript(self, video_id_or_url: str, title: str, segments: List[Dict[str, Any]]) -> Path:
        vid = self.extract_video_id(video_id_or_url) or re.sub(r"[^a-zA-Z0-9_\-]", "_", video_id_or_url)
        cache_file = self.transcript_dir / f"{vid}.json"
        payload = {"video_id": vid, "title": title, "segments": segments, "updated_at": time.time()}
        cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return cache_file

    def extract_youtube_transcript(self, url: str) -> Dict[str, Any]:
        clean_url = url.strip()
        if not clean_url.startswith("http"):
            clean_url = f"https://{clean_url}"

        vid = self.extract_video_id(clean_url) or hashlib.md5(clean_url.encode("utf-8")).hexdigest()[:11]
        cache_file = self.transcript_dir / f"{vid}.json"

        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                segs = cached.get("segments", [])
                formatted = [f"{self._format_ts(s.get('start', 0))} {s.get('text', '')}" for s in segs]
                return {
                    "video_id": vid,
                    "title": cached.get("title", f"YouTube Video {vid}"),
                    "segments": segs,
                    "formatted_transcript": "\n".join(formatted),
                    "source": "transcript_cache",
                }
            except Exception:
                pass

        title = f"YouTube Video ({vid})"
        segments: List[Dict[str, Any]] = []
        source = "none"

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            raw_list = YouTubeTranscriptApi.get_transcript(vid, languages=["en", "en-US", "en-GB"])
            segments = [{"start": float(item["start"]), "text": item["text"].strip()} for item in raw_list if item.get("text")]
            source = "youtube_transcript_api"
        except Exception:
            pass

        if not segments and shutil.which("yt-dlp"):
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    out_tmpl = str(Path(tmpdir) / "sub")
                    cmd = [
                        "yt-dlp", "--skip-download", "--write-auto-sub", "--write-sub",
                        "--sub-lang", "en.*", "--sub-format", "json3", "-o", out_tmpl, clean_url,
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12.0)
                    sub_files = list(Path(tmpdir).glob("*.json3"))
                    if sub_files:
                        sub_data = json.loads(sub_files[0].read_text(encoding="utf-8", errors="ignore"))
                        for ev in sub_data.get("events", []):
                            if "segs" in ev:
                                txt = "".join(s.get("utf8", "") for s in ev["segs"]).strip().replace("\n", " ")
                                if txt:
                                    start_sec = float(ev.get("tStartMs", 0)) / 1000.0
                                    segments.append({"start": start_sec, "text": txt})
                        if segments:
                            source = "yt_dlp_json3"
            except Exception:
                pass

        if not segments:
            desc = self.read_url_or_media(clean_url)
            segments = [{"start": 0.0, "text": f"Overview of {title}: {desc[:180]}"}]
            source = "metadata_fallback"

        self.register_local_transcript(vid, title, segments)
        formatted = [f"{self._format_ts(s['start'])} {s['text']}" for s in segments]
        return {
            "video_id": vid,
            "title": title,
            "segments": segments,
            "formatted_transcript": "\n".join(formatted),
            "source": source,
        }

    def read_url_or_media(self, url: str) -> str:
        clean_url = url.strip()
        if not clean_url.startswith("http"):
            clean_url = f"https://{clean_url}"
        try:
            req = urllib.request.Request(clean_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                raw_html = resp.read().decode("utf-8", errors="ignore")
                text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]
                return "\n".join(lines[:20])
        except Exception as e:
            return f"Error reading URL: {e}"

    # -------------------------------------------------------------------------
    # 3. Cross-Platform Notifications & Two-Way Message Reply Bridge
    # -------------------------------------------------------------------------
    def push_incoming_notification(self, app: str, sender: str, content: str, notif_id: Optional[str] = None) -> Dict[str, Any]:
        nid = notif_id or hashlib.md5(f"{app}:{sender}:{content}".encode("utf-8")).hexdigest()[:12]
        item = {
            "id": nid,
            "app": app.strip(),
            "sender": sender.strip(),
            "content": content.strip(),
            "timestamp": time.time(),
        }
        self._live_notification_queue.append(item)
        return item

    def collect_raw_os_notifications(self, app_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = list(self._live_notification_queue)

        if shutil.which("dunstctl"):
            try:
                out = subprocess.check_output(["dunstctl", "history"], stderr=subprocess.DEVNULL, timeout=2.0)
                data = json.loads(out.decode("utf-8", errors="ignore"))
                for item in data.get("data", [[]])[0]:
                    app = item.get("appname", {}).get("data", "Desktop")
                    summary = item.get("summary", {}).get("data", "")
                    body = item.get("body", {}).get("data", "")
                    nid = str(item.get("id", {}).get("data", hashlib.md5(f"{app}:{summary}:{body}".encode()).hexdigest()[:10]))
                    collected.append({"id": nid, "app": app, "sender": summary, "content": body})
            except Exception:
                pass

        if shutil.which("termux-notification-list"):
            try:
                out = subprocess.check_output(["termux-notification-list"], stderr=subprocess.DEVNULL, timeout=3.0)
                notifs = json.loads(out.decode("utf-8", errors="ignore"))
                for n in notifs:
                    pkg = n.get("packageName", "").lower()
                    app = pkg.split(".")[-1].capitalize() if "." in pkg else (pkg or "App")
                    title = n.get("title", "").strip()
                    content = n.get("content", "").strip()
                    if title or content:
                        nid = str(n.get("id", hashlib.md5(f"{app}:{title}:{content}".encode()).hexdigest()[:10]))
                        collected.append({"id": nid, "app": app, "sender": title, "content": content})
            except Exception:
                pass

        if app_filter:
            target = app_filter.lower().strip()
            collected = [
                c for c in collected
                if target in c["app"].lower() or target in c["sender"].lower() or target in c["content"].lower()
            ]
        return collected

    def read_notifications(self, app_filter: Optional[str] = None, limit: int = 5) -> str:
        items = self.collect_raw_os_notifications(app_filter=app_filter)
        if not items:
            return f"No unread notifications matching '{app_filter}'." if app_filter else "No unread notifications right now."
        return "\n".join(f"[{c['app']}] {c['sender']}: {c['content']}" for c in items[:limit])

    def send_or_reply_message(self, recipient: str, message_body: str, app: str = "WhatsApp") -> Dict[str, Any]:
        """Dispatches an outbound message/reply across OS notification hooks or Outbox Ledger,
        and logs it in the ActionJournal as IRREVERSIBLE.
        """
        clean_recipient = recipient.strip().title()
        clean_msg = message_body.strip().strip("'\"")
        clean_app = app.strip() or "WhatsApp"

        # Find matching active notification ID if replying to an incoming notification
        matched_notif_id = None
        for item in reversed(self._live_notification_queue):
            if clean_recipient.lower() in item["sender"].lower():
                matched_notif_id = item["id"]
                clean_app = item["app"]
                break

        transport = "UNIFIED_OUTBOX_BRIDGE"
        if matched_notif_id and shutil.which("termux-notification-reply"):
            try:
                subprocess.run(
                    ["termux-notification-reply", "-i", str(matched_notif_id), clean_msg],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0,
                )
                transport = "TERMUX_NOTIFICATION_INLINE_REPLY"
            except Exception:
                pass

        record = {
            "message_id": f"msg_{int(time.time() * 1000)}",
            "recipient": clean_recipient,
            "app": clean_app,
            "body": clean_msg,
            "reply_to_notification_id": matched_notif_id,
            "transport": transport,
            "timestamp": time.time(),
        }
        with self.outbox_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        enforce_owner_only_permissions(self.outbox_path)

        # Register as IRREVERSIBLE in the ActionJournal (sent messages cannot be unsent!)
        undo_ledger.register_undo(
            action_type="OUTBOUND_MESSAGE",
            description=f"Sent {clean_app} message to {clean_recipient}: '{clean_msg[:40]}'",
            rollback_fn=None,
            reversibility="IRREVERSIBLE",
            backup_payload=record,
        )

        spoken = (
            f"Dispatched {clean_app} reply to {clean_recipient}: \"{clean_msg}\" "
            f"(logged in Action Journal as IRREVERSIBLE)."
        )
        return {
            "intent": "SEND_MESSAGE_REPLY",
            "recipient": clean_recipient,
            "app": clean_app,
            "message": clean_msg,
            "reversibility": "IRREVERSIBLE",
            "spoken_response": spoken,
        }

    # -------------------------------------------------------------------------
    # 4. Document/Book Slicer & Persistent Reading Bookmark Tracker
    # -------------------------------------------------------------------------
    def resolve_file_path(self, filename: str) -> Optional[Path]:
        clean = filename.strip().strip("'\"")
        direct = Path(clean)
        if direct.is_file():
            return direct
        for root in [self.workspace, Path(".")]:
            matches = [p for p in root.rglob(f"*{clean}*") if p.is_file() and "__pycache__" not in str(p) and ".git" not in str(p)]
            if matches:
                return matches[0]
        return None

    def _extract_file_lines(self, p: Path) -> List[str]:
        ext = p.suffix.lower()
        if ext == ".pdf":
            return self._extract_pdf(p)
        if ext == ".docx":
            return self._extract_docx(p)
        return p.read_text(encoding="utf-8", errors="ignore").splitlines()

    def _save_bookmark(self, p: Path, start_line: int, end_line: int, total_lines: int) -> None:
        file_key = p.name.lower()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reading_bookmarks (
                    file_key, canonical_path, last_start_line, last_end_line, total_lines, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (file_key, str(p.resolve()), start_line, end_line, total_lines, time.time()),
            )
            conn.commit()

    def get_bookmark(self, filename_hint: str = "") -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            if filename_hint.strip():
                key = Path(filename_hint.strip()).name.lower()
                row = conn.execute("SELECT * FROM reading_bookmarks WHERE file_key LIKE ? ORDER BY updated_at DESC LIMIT 1", (f"%{key}%",)).fetchone()
            else:
                row = conn.execute("SELECT * FROM reading_bookmarks ORDER BY updated_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def read_document_slice(self, filename: str, start_line: int = 1, end_line: int = -1, save_bookmark: bool = True) -> str:
        p = self.resolve_file_path(filename)
        if not p or not p.exists():
            return f"File '{filename}' not found in workspace or project tree."

        lines = self._extract_file_lines(p)
        total = len(lines)
        if total == 0:
            return f"{p.name} is empty."

        s = max(1, start_line)
        e = total if end_line == -1 else min(total, end_line)
        if save_bookmark:
            self._save_bookmark(p, s, e, total)

        pct = int(round((e / total) * 100))
        slice_lines = lines[s - 1 : e]
        return f"Reading lines {s} to {e} of {total} ({pct}%) from {p.name}:\n" + "\n".join(slice_lines)

    def continue_reading_from_bookmark(self, filename_hint: str = "", chunk_size: int = 3) -> Dict[str, Any]:
        """Resumes reading a book/PDF/document from `last_end_line + 1` and updates the persistent bookmark."""
        bm = self.get_bookmark(filename_hint)
        if not bm:
            return {
                "intent": "READ_BOOKMARK_CONTINUE",
                "status": "no_bookmark",
                "spoken_response": f"No active reading bookmark found{f' for {filename_hint}' if filename_hint else ''}.",
            }

        p = Path(bm["canonical_path"])
        if not p.exists():
            return {
                "intent": "READ_BOOKMARK_CONTINUE",
                "status": "file_missing",
                "spoken_response": f"Bookmarked file {p.name} is no longer at {p}.",
            }

        lines = self._extract_file_lines(p)
        total = len(lines)
        prev_end = int(bm["last_end_line"])
        if prev_end >= total:
            return {
                "intent": "READ_BOOKMARK_CONTINUE",
                "file": p.name,
                "start_line": total,
                "end_line": total,
                "total_lines": total,
                "percent_complete": 100,
                "spoken_response": f"You have already finished reading {p.name} (line {total} of {total}, 100% complete).",
            }

        next_start = prev_end + 1
        next_end = min(total, next_start + chunk_size - 1)
        self._save_bookmark(p, next_start, next_end, total)
        pct = int(round((next_end / total) * 100))
        chunk_text = "\n".join(lines[next_start - 1 : next_end])

        spoken = f"Resuming {p.name} at lines {next_start} to {next_end} of {total} ({pct}% complete): {chunk_text}"
        return {
            "intent": "READ_BOOKMARK_CONTINUE",
            "file": p.name,
            "start_line": next_start,
            "end_line": next_end,
            "total_lines": total,
            "percent_complete": pct,
            "content": chunk_text,
            "spoken_response": spoken[:260],
        }


    def search_inside_document(self, filename: str, topic_query: str, window_lines: int = 3) -> Dict[str, Any]:
        """Semantically searches inside a book, PDF, DOCX, or code file for a topic/chapter,
        jumps directly to the best-matching line range, and updates the persistent reading bookmark.
        """
        from agent.pa_scaffolder.graph_brain import FastSemanticProjector

        p = self.resolve_file_path(filename)
        if not p or not p.exists():
            bm = self.get_bookmark(filename)
            if bm and Path(bm["canonical_path"]).exists():
                p = Path(bm["canonical_path"])
            else:
                return {
                    "intent": "BOOK_TOPIC_SEARCH",
                    "status": "not_found",
                    "spoken_response": f"Could not find document '{filename}' to search inside.",
                }

        lines = self._extract_file_lines(p)
        total = len(lines)
        if total == 0:
            return {"intent": "BOOK_TOPIC_SEARCH", "status": "empty", "spoken_response": f"{p.name} is empty."}

        clean_topic = re.sub(
            r"^(?:find|search|jump\s+to|go\s+to|locate)\s+(?:the\s+)?(?:section|chapter|part|passage|lines?)?\s*(?:about|on|for|where)?\s*",
            "",
            topic_query.strip(),
            flags=re.I,
        )
        clean_topic = re.sub(r"\s+(?:in|inside|from)\s+[a-zA-Z0-9_\-\./]+.*$", "", clean_topic, flags=re.I).strip("? ")

        q_vec = FastSemanticProjector.embed_text(clean_topic)
        q_tokens = [t for t in re.findall(r"[a-z0-9]{3,}", clean_topic.lower()) if t not in {"the", "and", "for", "with"}]

        best_idx = 0
        best_score = -1.0
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            window_text = " ".join(lines[i : min(total, i + window_lines)])
            l_vec = FastSemanticProjector.embed_text(window_text)
            sim = FastSemanticProjector.cosine_similarity(q_vec, l_vec)
            lower_win = window_text.lower()
            for tok in q_tokens:
                if tok in lower_win:
                    sim += 0.35
                if tok in line.lower():
                    sim += 0.25
            if sim > best_score:
                best_score = sim
                best_idx = i

        start_line = best_idx + 1
        end_line = min(total, start_line + window_lines - 1)
        self._save_bookmark(p, start_line, end_line, total)
        pct = int(round((end_line / total) * 100))
        passage = "\n".join(lines[start_line - 1 : end_line])

        spoken = (
            f"Jumped to '{clean_topic}' in {p.name} (lines {start_line} to {end_line} of {total}, {pct}% bookmark saved): "
            f"{passage[:180]}"
        )
        return {
            "intent": "BOOK_TOPIC_SEARCH",
            "file": p.name,
            "topic": clean_topic,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total,
            "percent_complete": pct,
            "content": passage,
            "score": round(float(best_score), 4),
            "spoken_response": spoken,
        }

    def search_live_web(self, query: str) -> Dict[str, Any]:
        """Searches live web sources (Wikipedia REST API, DuckDuckGo Instant Answer JSON, ArXiv)
        with automatic local GraphBrain & Research Vault synthesis when offline.
        """
        import urllib.parse
        from agent.pa_scaffolder.unified_memory_hub import memory_hub
        from agent.pa_scaffolder.graph_brain import NodeType

        clean_q = re.sub(
            r"^(?:please\s+)?(?:search\s+(?:the\s+)?web\s+for|search\s+online\s+for|look\s+up\s+online|web\s+search|google|search\s+for)\s+",
            "",
            query.strip(),
            flags=re.I,
        ).strip("? ")

        snippets: List[str] = []
        source_used = "live_web_api"

        # 1. Try DuckDuckGo Instant Answer JSON API
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(clean_q)}&format=json&no_html=1"
            req = urllib.request.Request(ddg_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if data.get("AbstractText"):
                    snippets.append(f"[DuckDuckGo] {data['AbstractText'][:220]}")
                for topic in data.get("RelatedTopics", [])[:2]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        snippets.append(f"[Web] {topic['Text'][:160]}")
        except Exception:
            pass

        # 2. Try Wikipedia REST Summary API
        if not snippets:
            try:
                wiki_slug = urllib.parse.quote(clean_q.replace(" ", "_"))
                wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_slug}"
                req = urllib.request.Request(wiki_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    wdata = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    if wdata.get("extract"):
                        snippets.append(f"[Wikipedia] {wdata['extract'][:220]}")
            except Exception:
                pass

        # 3. Local Knowledge & Research Vault Synthesis Fallback (Works 100% Offline)
        if not snippets:
            source_used = "local_knowledge_index"
            hits = memory_hub.graph_brain.get_relevant_context(clean_q, top_k=2)
            papers = memory_hub.research_memory.search_papers(clean_q, limit=2)
            for p in papers:
                snippets.append(f"[Research Index] {p['title']} ({p['year']}): {p['abstract'][:150]}")
            for h in hits:
                snippets.append(f"[GraphBrain] {h['label']}: {h['content'][:150]}")
            if not snippets:
                snippets.append(f"Synthesized reference for '{clean_q}': indexed into research graph for active tracking.")

        combined = " | ".join(snippets[:2])
        node_id = f"web_{hashlib.md5(clean_q.lower().encode()).hexdigest()[:10]}"
        memory_hub.graph_brain.add_or_update_node(
            node_id=node_id,
            node_type=NodeType.RESEARCH,
            metadata={"query": clean_q, "summary": combined, "source": source_used},
            label=f"WebSearch_{clean_q[:30]}",
            sync_obsidian=True,
        )

        return {
            "intent": "WEB_SEARCH_RESULT",
            "query": clean_q,
            "source": source_used,
            "snippets": snippets,
            "taint_level": "UNTRUSTED_EXTERNAL",
            "spoken_response": f"Web & Knowledge Search for '{clean_q}' ({source_used}): {combined[:220]}",
        }

    def _extract_pdf(self, path: Path) -> List[str]:
        for mod_name in ["fitz", "pypdf"]:
            try:
                if mod_name == "fitz":
                    import fitz
                    doc = fitz.open(str(path))
                    return [l.strip() for page in doc for l in page.get_text().splitlines() if l.strip()]
                else:
                    import pypdf
                    reader = pypdf.PdfReader(str(path))
                    return [l.strip() for page in reader.pages for l in (page.extract_text() or "").splitlines() if l.strip()]
            except ImportError:
                continue
        if shutil.which("pdftotext"):
            try:
                out = subprocess.check_output(["pdftotext", str(path), "-"], stderr=subprocess.DEVNULL)
                return [l.strip() for l in out.decode("utf-8", errors="ignore").splitlines() if l.strip()]
            except Exception:
                pass
        return [f"(Binary PDF {path.name}: install pypdf or poppler to extract text)"]

    def _extract_docx(self, path: Path) -> List[str]:
        try:
            import docx
            doc = docx.Document(str(path))
            return [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        except ImportError:
            return [f"(DOCX {path.name}: install python-docx to extract text)"]

    def read_clipboard(self) -> str:
        for cmd in [
            ["wl-paste"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["pbpaste"],
            ["termux-clipboard-get"],
        ]:
            if shutil.which(cmd[0]):
                try:
                    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2.0).decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue
        if desktop_controller:
            try:
                text = desktop_controller.get_clipboard()
                if text and text.strip():
                    return text.strip()
            except Exception:
                pass
        return "Clipboard is empty."


universal_reader = UniversalReader()
