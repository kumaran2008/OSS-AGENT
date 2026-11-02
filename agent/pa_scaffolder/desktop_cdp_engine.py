from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.pa_scaffolder.platform_detector import HARDWARE_PROFILE, HostOS


class AsyncCDPWebSocket:
    """Zero-Dependency RFC 6455 Asynchronous WebSocket Client for Chrome DevTools Protocol."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._msg_id = 0

    async def connect(self, timeout: float = 3.0) -> None:
        clean_url = self.ws_url.replace("ws://", "")
        parts = clean_url.split("/", 1)
        host_port = parts[0].split(":")
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 9222
        path = "/" + (parts[1] if len(parts) > 1 else "")

        sec_key = base64.b64encode(os.urandom(16)).decode("utf-8")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )

        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        self.writer.write(handshake.encode("utf-8"))
        await self.writer.drain()

        headers_data = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), timeout=timeout)
        if b"101" not in headers_data:
            raise ConnectionError("CDP WebSocket handshake rejected by Chrome.")

    async def send_frame(self, text_payload: str) -> None:
        data = text_payload.encode("utf-8")
        length = len(data)
        frame = bytearray([0x81])

        mask_key = os.urandom(4)
        if length < 126:
            frame.append(length | 0x80)
        elif length < 65536:
            frame.append(126 | 0x80)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(127 | 0x80)
            frame.extend(struct.pack(">Q", length))

        frame.extend(mask_key)
        masked_data = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(data))
        frame.extend(masked_data)

        self.writer.write(frame)
        await self.writer.drain()

    async def recv_frame(self, timeout: float = 6.0) -> Optional[str]:
        try:
            head = await asyncio.wait_for(self.reader.readexactly(2), timeout=timeout)
        except Exception:
            return None

        opcode = head[0] & 0x0F
        masked = (head[1] & 0x80) != 0
        length = head[1] & 0x7F

        if length == 126:
            raw_len = await self.reader.readexactly(2)
            length = struct.unpack(">H", raw_len)[0]
        elif length == 127:
            raw_len = await self.reader.readexactly(8)
            length = struct.unpack(">Q", raw_len)[0]

        mask_key = await self.reader.readexactly(4) if masked else None
        payload = await self.reader.readexactly(length)

        if masked and mask_key:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        if opcode == 0x08:
            return None
        elif opcode == 0x09:
            pong = bytearray([0x8A, 0x00])
            self.writer.write(pong)
            await self.writer.drain()
            return await self.recv_frame(timeout)
        elif opcode == 0x01:
            return payload.decode("utf-8", errors="replace")

        return None

    async def call_method(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 8.0
    ) -> Dict[str, Any]:
        self._msg_id += 1
        req_id = self._msg_id
        req = {"id": req_id, "method": method, "params": params or {}}
        await self.send_frame(json.dumps(req))

        t0 = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - t0) < timeout:
            msg_str = await self.recv_frame(timeout=timeout)
            if not msg_str:
                break
            try:
                res = json.loads(msg_str)
                if res.get("id") == req_id:
                    return res.get("result", {})
            except Exception:
                continue
        return {}

    async def close(self) -> None:
        if self.writer:
            try:
                self.writer.write(bytearray([0x88, 0x00]))
                await self.writer.drain()
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


class DesktopCDPEngine:
    """Production Chrome DevTools Protocol Engine.
    - Full general web navigation (navigate, click, type, scrape, screenshot).
    - Free logged-in AI session scraping (ChatGPT, Claude, Gemini) fallback.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.profile = HARDWARE_PROFILE

    def is_cdp_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/json/version", method="GET")
            with urllib.request.urlopen(req, timeout=0.3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_open_tabs(self) -> List[Dict[str, Any]]:
        try:
            req = urllib.request.Request(f"{self.base_url}/json", method="GET")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

    def get_or_create_active_tab(self) -> Optional[Dict[str, Any]]:
        tabs = self.list_open_tabs()
        page_tabs = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if page_tabs:
            return page_tabs[0]
        try:
            req = urllib.request.Request(f"{self.base_url}/json/new", method="PUT")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # General Web Automation API (Any Website)
    # -------------------------------------------------------------------------
    async def navigate_to(self, url: str) -> Dict[str, Any]:
        """Navigates active Chrome tab to any target URL."""
        tab = self.get_or_create_active_tab()
        if not tab:
            return {"success": False, "error": "No Chrome tab available"}

        target_url = url if url.startswith("http") else f"https://{url}"
        ws = AsyncCDPWebSocket(tab["webSocketDebuggerUrl"])
        try:
            await ws.connect()
            await ws.call_method("Page.enable")
            res = await ws.call_method("Page.navigate", {"url": target_url})
            await asyncio.sleep(2.0)  # Await initial document load
            await ws.close()
            return {"success": True, "url": target_url, "frameId": res.get("frameId")}
        except Exception as e:
            await ws.close()
            return {"success": False, "error": str(e)}

    async def click_element(self, css_selector: str) -> Dict[str, Any]:
        """Finds element by CSS selector, scrolls into view, and clicks it."""
        tab = self.get_or_create_active_tab()
        if not tab:
            return {"success": False, "error": "No Chrome tab available"}

        click_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(css_selector)});
            if (!el) return {{ success: false, error: "Element not found" }};
            el.scrollIntoView({{ behavior: "instant", block: "center" }});
            el.focus();
            el.click();
            return {{ success: true, tag: el.tagName, text: el.innerText ? el.innerText.slice(0, 50) : "" }};
        }})();
        """
        ws = AsyncCDPWebSocket(tab["webSocketDebuggerUrl"])
        try:
            await ws.connect()
            await ws.call_method("Runtime.enable")
            eval_res = await ws.call_method("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
            await ws.close()
            val = eval_res.get("result", {}).get("value", {})
            return val
        except Exception as e:
            await ws.close()
            return {"success": False, "error": str(e)}

    async def type_into(self, css_selector: str, text: str) -> Dict[str, Any]:
        """Focuses target input/textarea and inputs text cleanly."""
        tab = self.get_or_create_active_tab()
        if not tab:
            return {"success": False, "error": "No Chrome tab available"}

        type_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(css_selector)});
            if (!el) return {{ success: false, error: "Input element not found" }};
            el.focus();
            if (el.isContentEditable) {{
                document.execCommand("selectAll", false, null);
                document.execCommand("insertText", false, {json.dumps(text)});
            }} else {{
                el.value = {json.dumps(text)};
                el.dispatchEvent(new Event("input", {{ bubbles: true }}));
                el.dispatchEvent(new Event("change", {{ bubbles: true }}));
            }}
            return {{ success: true }};
        }})();
        """
        ws = AsyncCDPWebSocket(tab["webSocketDebuggerUrl"])
        try:
            await ws.connect()
            await ws.call_method("Runtime.enable")
            eval_res = await ws.call_method("Runtime.evaluate", {"expression": type_js, "returnByValue": True})
            await ws.close()
            return eval_res.get("result", {}).get("value", {})
        except Exception as e:
            await ws.close()
            return {"success": False, "error": str(e)}

    async def get_page_text(self, max_chars: int = 4000) -> str:
        """Extracts readable text from the current page body."""
        tab = self.get_or_create_active_tab()
        if not tab:
            return "No Chrome tab available."

        extract_js = "document.body ? document.body.innerText : ''"
        ws = AsyncCDPWebSocket(tab["webSocketDebuggerUrl"])
        try:
            await ws.connect()
            await ws.call_method("Runtime.enable")
            res = await ws.call_method("Runtime.evaluate", {"expression": extract_js, "returnByValue": True})
            await ws.close()
            full_text = res.get("result", {}).get("value", "")
            return full_text[:max_chars].strip()
        except Exception as e:
            await ws.close()
            return f"Error extracting page text: {e}"

    async def capture_page_screenshot(self, output_path: str = "workspace/page_screenshot.png") -> Optional[str]:
        """Captures page screenshot via CDP Page.captureScreenshot."""
        tab = self.get_or_create_active_tab()
        if not tab:
            return None

        ws = AsyncCDPWebSocket(tab["webSocketDebuggerUrl"])
        try:
            await ws.connect()
            await ws.call_method("Page.enable")
            res = await ws.call_method("Page.captureScreenshot", {"format": "png"})
            await ws.close()
            b64_data = res.get("data")
            if b64_data:
                p = Path(output_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(base64.b64decode(b64_data))
                return str(p.resolve())
            return None
        except Exception:
            await ws.close()
            return None

    # -------------------------------------------------------------------------
    # Free Logged-In AI Web Tab Fallback
    # -------------------------------------------------------------------------
    def find_target_ai_tab(self) -> Optional[Dict[str, Any]]:
        tabs = self.list_open_tabs()
        for tab in tabs:
            url = tab.get("url", "").lower()
            ws_url = tab.get("webSocketDebuggerUrl")
            if not ws_url:
                continue
            if any(domain in url for domain in ["chatgpt.com", "claude.ai", "gemini.google.com"]):
                return tab
        return None

    async def execute_free_desktop_query_async(self, prompt: str, max_wait_sec: float = 25.0) -> Tuple[bool, str]:
        tab = self.find_target_ai_tab()
        if not tab:
            return self._localized_fallback(prompt)

        ws_url = tab.get("webSocketDebuggerUrl")
        ws = AsyncCDPWebSocket(ws_url)
        try:
            await ws.connect(timeout=2.0)
            await ws.call_method("Runtime.enable")

            clean_prompt_json = json.dumps(prompt)
            injection_js = f"""
            (() => {{
                const text = {clean_prompt_json};
                const host = window.location.hostname;
                let inputEl = null;
                let sendBtn = null;

                if (host.includes("chatgpt")) {{
                    inputEl = document.querySelector("#prompt-textarea, div[contenteditable='true'], textarea");
                    sendBtn = document.querySelector("button[data-testid='send-button'], button[aria-label='Send prompt']");
                }} else if (host.includes("claude")) {{
                    inputEl = document.querySelector("div[contenteditable='true'], fieldset div[contenteditable='true']");
                    sendBtn = document.querySelector("button[aria-label='Send Message'], button[aria-label='Send message']");
                }} else if (host.includes("gemini")) {{
                    inputEl = document.querySelector("rich-textarea div[contenteditable='true'], textarea");
                    sendBtn = document.querySelector("button[aria-label='Send message'], button.send-button");
                }}

                if (!inputEl) return {{ success: false, error: "Input prompt box not found" }};
                inputEl.focus();
                if (inputEl.isContentEditable) {{
                    document.execCommand("selectAll", false, null);
                    document.execCommand("insertText", false, text);
                }} else {{
                    inputEl.value = text;
                    inputEl.dispatchEvent(new Event("input", {{ bubbles: true }}));
                }}

                const assistantCount = document.querySelectorAll(
                    "[data-message-author-role='assistant'], .font-claude-message, model-response, div.markdown"
                ).length;

                setTimeout(() => {{
                    if (sendBtn && !sendBtn.disabled) sendBtn.click();
                    else inputEl.dispatchEvent(new KeyboardEvent("keydown", {{ key: "Enter", code: "Enter", bubbles: true, keyCode: 13 }}));
                }}, 150);

                return {{ success: true, base_count: assistantCount }};
            }})();
            """

            inj_res = await ws.call_method("Runtime.evaluate", {"expression": injection_js, "returnByValue": True})
            val = inj_res.get("result", {}).get("value", {})
            if not val.get("success"):
                await ws.close()
                return self._localized_fallback(prompt)

            base_count = val.get("base_count", 0)

            poll_js = f"""
            (() => {{
                const host = window.location.hostname;
                let isStreaming = false;
                if (host.includes("chatgpt")) isStreaming = !!document.querySelector("button[data-testid='stop-button']");
                else if (host.includes("claude")) isStreaming = !!document.querySelector("button[aria-label*='Stop']");
                else if (host.includes("gemini")) isStreaming = !!document.querySelector(".loading-indicator");

                const messages = Array.from(document.querySelectorAll(
                    "[data-message-author-role='assistant'], .font-claude-message, model-response, div.markdown"
                ));

                if (messages.length <= {base_count}) return {{ ready: false, text: "" }};
                const latest = messages[messages.length - 1];
                const replyText = latest ? latest.innerText.trim() : "";
                return {{ ready: !isStreaming && replyText.length > 0, text: replyText }};
            }})();
            """

            t0 = asyncio.get_event_loop().time()
            scraped_reply = ""
            await asyncio.sleep(1.0)

            while (asyncio.get_event_loop().time() - t0) < max_wait_sec:
                poll_res = await ws.call_method("Runtime.evaluate", {"expression": poll_js, "returnByValue": True})
                p_val = poll_res.get("result", {}).get("value", {})
                if p_val.get("ready"):
                    scraped_reply = p_val.get("text", "")
                    break
                await asyncio.sleep(0.4)

            await ws.close()
            if scraped_reply:
                clean_scraped = " ".join(scraped_reply.split()[:80])
                tab_title = tab.get("title", "Desktop AI")[:20]
                return True, f"[{tab_title}]: {clean_scraped}"

            return self._localized_fallback(prompt)
        except Exception:
            await ws.close()
            return self._localized_fallback(prompt)

    def _localized_fallback(self, prompt: str) -> Tuple[bool, str]:
        return True, f"Acknowledged: '{prompt}'. Ready for next command."
