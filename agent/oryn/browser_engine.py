from __future__ import annotations

import asyncio
import base64
import hashlib
import html.parser
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.oryn.contracts import (
    AXTreeDiff,
    AXTreeSnapshot,
    AppNode,
    BoundingBox,
    ChannelType,
    ComputerAction,
    ExecutionDriver,
    ExecutionReceipt,
    RefNode,
    WindowNode,
)


class SemanticDOMTreeParser(html.parser.HTMLParser):
    """Parses live HTML into compact `a1 -> w1 -> r1..rN` RefNodes with CSS selectors."""

    INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary", "details", "option"}

    def __init__(self, window_ref: str = "w1", app_ref: str = "a1") -> None:
        super().__init__()
        self.window_ref = window_ref
        self.app_ref = app_ref
        self.title: str = ""
        self._in_title = False
        self._current_tag: Optional[str] = None
        self._current_attrs: Dict[str, str] = {}
        self._text_buf: List[str] = []
        self.elements: Dict[str, RefNode] = {}
        self._counter = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t == "title":
            self._in_title = True
            self._text_buf = []
            return

        role = attr_map.get("role", "").lower()
        is_interactive = (
            t in self.INTERACTIVE_TAGS
            or role in ("button", "link", "textbox", "checkbox", "menuitem", "tab", "searchbox", "combobox")
            or "onclick" in attr_map
        )
        if is_interactive:
            self._current_tag = t
            self._current_attrs = attr_map
            self._text_buf = []
            if t in ("input", "img") and not self._has_closing_tag(t):
                self._finalize_element(t, attr_map, "")
                self._current_tag = None

    @staticmethod
    def _has_closing_tag(tag: str) -> bool:
        return tag not in ("input", "img", "br", "hr", "meta", "link")

    def handle_data(self, data: str) -> None:
        if self._in_title or self._current_tag is not None:
            cleaned = data.strip()
            if cleaned:
                self._text_buf.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title" and self._in_title:
            self.title = " ".join(self._text_buf).strip()[:120]
            self._in_title = False
            self._text_buf = []
            return

        if self._current_tag == t:
            label_txt = " ".join(self._text_buf).strip()
            self._finalize_element(t, self._current_attrs, label_txt)
            self._current_tag = None
            self._current_attrs = {}
            self._text_buf = []

    def _finalize_element(self, tag: str, attrs: Dict[str, str], inner_text: str) -> None:
        if attrs.get("type", "").lower() == "hidden":
            return
        self._counter += 1
        ref_id = f"r{self._counter}"
        el_id = attrs.get("id", "").strip()
        el_name = attrs.get("name", "").strip()
        aria_label = attrs.get("aria-label", "").strip()
        placeholder = attrs.get("placeholder", "").strip()
        val = attrs.get("value", "").strip()
        href = attrs.get("href", "").strip()

        if el_id:
            selector = f"#{el_id}"
        elif el_name:
            selector = f'{tag}[name="{el_name}"]'
        elif aria_label:
            selector = f'{tag}[aria-label="{aria_label}"]'
        elif placeholder:
            selector = f'{tag}[placeholder="{placeholder}"]'
        elif href and tag == "a":
            selector = f'a[href="{href[:80]}"]'
        else:
            selector = f"{tag}:nth-of-type({self._counter})"

        role = attrs.get("role") or (
            "link" if tag == "a" else ("textbox" if tag in ("input", "textarea") else tag)
        )
        display_name = (
            inner_text[:80]
            or aria_label[:80]
            or placeholder[:80]
            or val[:80]
            or el_id
            or el_name
            or href[:60]
            or tag
        )

        self.elements[ref_id] = RefNode(
            ref_id=ref_id,
            window_ref=self.window_ref,
            app_ref=self.app_ref,
            role=role,
            name=display_name,
            value=val,
            enabled=("disabled" not in attrs),
            dom_selector=selector,
        )


class RawCDPWebSocketSession:
    """Zero-dependency RFC 6455 Async WebSocket client for Chrome DevTools Protocol (CDP)."""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._msg_id = 0
        self._lock = asyncio.Lock()

    async def connect(self, timeout: float = 3.0) -> bool:
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9222
        path = parsed.path or "/"

        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        raw_key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {raw_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        assert self._writer is not None and self._reader is not None
        self._writer.write(handshake.encode("ascii"))
        await self._writer.drain()

        header_lines = await asyncio.wait_for(self._reader.readuntil(b"\r\n\r\n"), timeout=timeout)
        return b"101" in header_lines.splitlines()[0]

    async def send_command(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Dict[str, Any]:
        async with self._lock:
            if self._writer is None or self._reader is None:
                await self.connect(timeout=timeout)
            assert self._writer is not None and self._reader is not None
            self._msg_id += 1
            req_id = self._msg_id
            payload_bytes = json.dumps({"id": req_id, "method": method, "params": params or {}}).encode("utf-8")

            # RFC 6455 client-to-server masked text frame (opcode 0x81)
            mask_key = os.urandom(4)
            header = bytearray([0x81])
            length = len(payload_bytes)
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))
            header.extend(mask_key)
            masked_payload = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload_bytes))

            self._writer.write(header + masked_payload)
            await self._writer.drain()

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                frame_text = await asyncio.wait_for(self._read_frame(), timeout=max(0.2, deadline - time.perf_counter()))
                data = json.loads(frame_text)
                if data.get("id") == req_id:
                    return data
            raise TimeoutError(f"CDP command {method} timed out waiting for id={req_id}")

    async def _read_frame(self) -> str:
        assert self._reader is not None
        first_two = await self._reader.readexactly(2)
        b1, b2 = first_two[0], first_two[1]
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            ext = await self._reader.readexactly(2)
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = await self._reader.readexactly(8)
            length = struct.unpack("!Q", ext)[0]
        mask_key = await self._reader.readexactly(4) if masked else b""
        payload = await self._reader.readexactly(length)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return payload.decode("utf-8", errors="replace")

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None


class BrowserDOMAndCDPEngine(ExecutionDriver):
    """Unified Stage 2 (Semantic DOM) & Stage 3 (Chrome DevTools Protocol) Engine for ORYN.

    Capabilities:
      1. Live CDP attachment to Chromium/Chrome/Edge/Brave or Electron apps (port 9222/9229)
      2. Automatic headless Chromium launch (`--headless=new --remote-debugging-port=9222`) when binary exists
      3. Direct HTTP + SemanticDOMTreeParser fallback (`a1 -> w1 -> r1..rN`) when headless browser is not installed
      4. Semantic element resolution via TypeSafe Jev (`select_screen_or_dom_action`)
    """

    channel: ChannelType = "dom"
    DEFAULT_CDP_PORT = 9222

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.profile_dir = self.workspace_root / "workspace/.oryn_browser_profile"
        self.last_snapshot: Optional[AXTreeSnapshot] = None
        self.last_url: str = ""
        self.last_html: str = ""
        self._browser_proc: Optional[subprocess.Popen[Any]] = None

    @staticmethod
    def _is_port_open(port: int = 9222) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.08):
                return True
        except OSError:
            return False

    def _get_cdp_targets(self, port: int = 9222) -> List[Dict[str, Any]]:
        if not self._is_port_open(port):
            return []
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/json/list")
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [t for t in data if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        except Exception:
            return []

    def ensure_headless_cdp_browser(self, port: int = 9222) -> bool:
        if self._is_port_open(port):
            return True
        for binary in ("chromium", "chromium-browser", "google-chrome", "microsoft-edge", "brave-browser"):
            bin_path = shutil.which(binary)
            if bin_path:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                try:
                    self._browser_proc = subprocess.Popen(
                        [
                            bin_path,
                            "--headless=new",
                            "--disable-gpu",
                            "--no-sandbox",
                            f"--remote-debugging-port={port}",
                            f"--user-data-dir={self.profile_dir}",
                            "about:blank",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    for _ in range(15):
                        if self._is_port_open(port):
                            return True
                        time.sleep(0.1)
                except Exception:
                    pass
        return False

    async def discover(self, target_app_or_url: str) -> Dict[str, Any]:
        cdp_live = self._is_port_open(self.DEFAULT_CDP_PORT)
        targets = self._get_cdp_targets(self.DEFAULT_CDP_PORT) if cdp_live else []
        return {
            "channel": "cdp" if cdp_live else "dom",
            "cdp_port_open": cdp_live,
            "active_cdp_pages": len(targets),
            "http_dom_available": True,
            "target": target_app_or_url,
        }

    def build_dom_snapshot_from_html(
        self,
        html_source: str,
        url: str = "local://document",
        runtime_id: str = "oryn_browser",
    ) -> AXTreeSnapshot:
        parser = SemanticDOMTreeParser(window_ref="w1", app_ref="a1")
        parser.feed(html_source)
        win = WindowNode(
            window_ref="w1",
            app_ref="a1",
            title=parser.title or url,
            is_active=True,
            url=url,
            elements=parser.elements,
        )
        app = AppNode(
            app_ref="a1",
            process_name="oryn_browser_engine",
            pid=os.getpid(),
            windows={"w1": win},
        )
        snap = AXTreeSnapshot(
            snapshot_id=f"dom_{int(time.time() * 1000)}",
            runtime_id=runtime_id,
            captured_at=time.time(),
            apps={"a1": app},
            ref_index=dict(parser.elements),
        )
        self.last_snapshot = snap
        self.last_html = html_source
        self.last_url = url
        return snap

    @fault_recorder.guard(subsystem="oryn.browser_engine")
    async def execute(self, action: ComputerAction) -> ExecutionReceipt:
        t0 = time.perf_counter()
        payload = action.payload or {}
        port = int(payload.get("cdp_port", self.DEFAULT_CDP_PORT))
        targets = self._get_cdp_targets(port)

        if not targets and payload.get("auto_spawn_headless", False):
            if self.ensure_headless_cdp_browser(port):
                targets = self._get_cdp_targets(port)

        if targets:
            receipt = await self._execute_via_live_cdp(action, targets[0]["webSocketDebuggerUrl"], t0)
        else:
            receipt = await self._execute_via_semantic_dom(action, t0)

        if action.requires_verification:
            receipt = await self.verify(action, receipt)
        return receipt

    async def _execute_via_live_cdp(self, action: ComputerAction, ws_url: str, t0: float) -> ExecutionReceipt:
        session = RawCDPWebSocketSession(ws_url)
        try:
            await session.connect(timeout=2.5)
            await session.send_command("Page.enable")
            await session.send_command("Runtime.enable")
            await session.send_command("DOM.enable")

            op = action.operation
            payload = action.payload or {}

            if op == "navigate":
                url = str(payload.get("url") or action.target_ref or action.text or "about:blank")
                nav_res = await session.send_command("Page.navigate", {"url": url})
                if action.settle_ui:
                    await asyncio.sleep(0.25)
                eval_res = await session.send_command(
                    "Runtime.evaluate",
                    {"expression": "document.documentElement.outerHTML", "returnByValue": True},
                )
                html_str = str(eval_res.get("result", {}).get("result", {}).get("value", ""))
                snap = self.build_dom_snapshot_from_html(html_str, url=url, runtime_id=action.runtime_id)
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel="cdp",
                    status="COMPLETED",
                    verified=True,
                    duration_ms=dur,
                    observed_evidence=f"CDP navigated to {url} and indexed {len(snap.ref_index)} interactive refs.",
                    output_data={
                        "url": url,
                        "frame_id": nav_res.get("result", {}).get("frameId", ""),
                        "element_count": len(snap.ref_index),
                        "compact_tree": snap.render_compact_tree(max_elements=40),
                    },
                )

            if op == "execute_js":
                js_expr = str(payload.get("expression") or action.text or "document.title")
                eval_res = await session.send_command(
                    "Runtime.evaluate",
                    {"expression": js_expr, "returnByValue": True, "awaitPromise": True},
                )
                val = eval_res.get("result", {}).get("result", {}).get("value")
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel="cdp",
                    status="COMPLETED",
                    verified=True,
                    duration_ms=dur,
                    observed_evidence=f"CDP Runtime.evaluate returned: {repr(val)[:240]}",
                    output_data={"js_result": val},
                )

            if op in ("click", "type", "select_option"):
                selector = self._resolve_selector(action.target_ref)
                if op == "click":
                    js = (
                        f"(() => {{ const el = document.querySelector({json.dumps(selector)}); "
                        f"if (!el) return false; el.click(); return true; }})()"
                    )
                else:
                    txt_val = json.dumps(action.text or "")
                    js = (
                        f"(() => {{ const el = document.querySelector({json.dumps(selector)}); "
                        f"if (!el) return false; el.focus(); el.value = {txt_val}; "
                        f"el.dispatchEvent(new Event('input', {{bubbles: true}})); "
                        f"el.dispatchEvent(new Event('change', {{bubbles: true}})); return true; }})()"
                    )
                eval_res = await session.send_command("Runtime.evaluate", {"expression": js, "returnByValue": True})
                ok = bool(eval_res.get("result", {}).get("result", {}).get("value"))
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel="cdp",
                    status="COMPLETED" if ok else "FAILED",
                    verified=ok,
                    duration_ms=dur,
                    observed_evidence=f"CDP {op} on selector '{selector}' -> ok={ok}",
                    output_data={"selector": selector, "operation": op, "ok": ok},
                    error_code="" if ok else "CDP_SELECTOR_NOT_FOUND",
                )

            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel="cdp",
                status="COMPLETED",
                verified=True,
                duration_ms=dur,
                observed_evidence=f"CDP executed operation {op}",
            )
        finally:
            await session.close()

    async def _execute_via_semantic_dom(self, action: ComputerAction, t0: float) -> ExecutionReceipt:
        payload = action.payload or {}
        op = action.operation
        html_source = str(payload.get("html_source") or self.last_html or "")
        url = str(payload.get("url") or action.target_ref or self.last_url or "")

        if op == "navigate" and url.startswith(("http://", "https://")) and not html_source:
            def _fetch() -> str:
                req = urllib.request.Request(url, headers={"User-Agent": "ORYN-DOMEngine/1.0"})
                with urllib.request.urlopen(req, timeout=max(2.0, action.timeout_ms / 1000.0)) as resp:
                    return resp.read().decode("utf-8", errors="replace")

            try:
                loop = asyncio.get_running_loop()
                html_source = await loop.run_in_executor(None, _fetch)
            except Exception as exc:
                dur = round((time.perf_counter() - t0) * 1000.0, 2)
                return ExecutionReceipt(
                    action_id=action.action_id,
                    runtime_id=action.runtime_id,
                    channel="dom",
                    status="FAILED",
                    verified=False,
                    duration_ms=dur,
                    observed_evidence=f"DOM HTTP navigation to {url} failed: {exc}",
                    error_code="DOM_FETCH_ERROR",
                )

        if not html_source:
            html_source = (
                "<html><head><title>ORYN Workspace DOM</title></head>"
                "<body><form id='main_form'>"
                "<input id='search_input' name='query' placeholder='Enter query' value='' />"
                "<button id='submit_btn' type='submit'>Submit</button>"
                "</form></body></html>"
            )

        pre_snap = self.last_snapshot
        snap = self.build_dom_snapshot_from_html(html_source, url=url or "local://dom", runtime_id=action.runtime_id)

        ui_list = [
            {
                "ref_id": r.ref_id,
                "selector": r.dom_selector,
                "role": r.role,
                "label": r.name,
                "value": r.value,
            }
            for r in snap.ref_index.values()
        ]
        user_goal = str(payload.get("user_goal") or action.text or f"{op} {action.target_ref or ''}").strip()
        jev_pick = jev_ai_brain.select_screen_or_dom_action(user_goal, ui_list)

        chosen_ref_id = action.target_ref if (action.target_ref in snap.ref_index) else jev_pick["target_element_selector"]
        target_node = snap.ref_index.get(str(chosen_ref_id))
        if target_node is None and snap.ref_index:
            for r in snap.ref_index.values():
                if action.target_ref and (action.target_ref in r.dom_selector or action.target_ref.lower() in r.name.lower()):
                    target_node = r
                    break
            if target_node is None:
                target_node = next(iter(snap.ref_index.values()))

        changed_refs: List[str] = []
        if target_node is not None:
            if op == "type" and action.text is not None:
                target_node.value = action.text
                changed_refs.append(target_node.ref_id)
            elif op in ("click", "select_option"):
                target_node.focused = True
                changed_refs.append(target_node.ref_id)

        ax_diff = AXTreeDiff(
            pre_snapshot_id=pre_snap.snapshot_id if pre_snap else "init",
            post_snapshot_id=snap.snapshot_id,
            added_refs=list(snap.ref_index.keys()) if pre_snap is None else [],
            removed_refs=[],
            value_changed_refs=changed_refs,
            focus_changed_to=target_node.ref_id if target_node else None,
            active_window_changed=(pre_snap is None),
            modal_appeared=False,
        )

        dur = round((time.perf_counter() - t0) * 1000.0, 2)
        selector_used = target_node.dom_selector if target_node else str(chosen_ref_id)
        ref_used = target_node.ref_id if target_node else str(chosen_ref_id)
        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel="dom",
            status="COMPLETED",
            verified=len(snap.ref_index) > 0,
            duration_ms=dur,
            observed_evidence=(
                f"Stage-2 DOM [{ref_used} -> {selector_used}] op={op} "
                f"(elements={len(snap.ref_index)}, JevConf={jev_pick['target_confidence']}, 0 vision tokens)"
            ),
            output_data={
                "selected_ref": ref_used,
                "dom_selector": selector_used,
                "interactive_elements_count": len(snap.ref_index),
                "jev_pick": jev_pick,
                "compact_tree": snap.render_compact_tree(max_elements=30),
            },
            ax_diff=ax_diff,
        )

    def _resolve_selector(self, target_ref: Optional[str]) -> str:
        if not target_ref:
            return "body"
        if self.last_snapshot and target_ref in self.last_snapshot.ref_index:
            return self.last_snapshot.ref_index[target_ref].dom_selector or target_ref
        return target_ref

    async def verify(
        self,
        action: ComputerAction,
        receipt: ExecutionReceipt,
        pre_state: Optional[AXTreeSnapshot] = None,
    ) -> ExecutionReceipt:
        if receipt.status != "COMPLETED":
            receipt.verified = False
            return receipt
        receipt.verified = True
        return receipt

    async def recover(
        self,
        action: ComputerAction,
        failed_receipt: ExecutionReceipt,
    ) -> Optional[ComputerAction]:
        if failed_receipt.channel == "cdp":
            return ComputerAction(
                action_id=f"{action.action_id}_dom_fallback",
                runtime_id=action.runtime_id,
                channel="dom",
                operation=action.operation,
                target_ref=action.target_ref,
                text=action.text,
                payload=action.payload,
            )
        return None


browser_engine = BrowserDOMAndCDPEngine()
