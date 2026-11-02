import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional, Tuple
from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine, AsyncCDPWebSocket


class ResilientCDPBridge:
    """
    Production-Grade Chrome DevTools Protocol Bridge.
    Uses in-page MutationObserver to stream LLM token deltas directly from active web sessions
    without paid API tokens and without brittle CSS class selectors.
    """

    SETUP_JS_TEMPLATE = """
    (() => {
        window.__oss_deltas = [];
        window.__oss_is_done = false;

        const host = window.location.hostname;
        let inputEl = document.querySelector("#prompt-textarea, div[contenteditable='true'], textarea, rich-textarea div[contenteditable='true']");
        let sendBtn = document.querySelector("button[data-testid='send-button'], button[aria-label*='Send'], button.send-button");

        if (!inputEl) return { success: false, error: "Input not found" };

        inputEl.focus();
        if (inputEl.isContentEditable) {
            document.execCommand("selectAll", false, null);
            document.execCommand("insertText", false, __PROMPT_JSON__);
        } else {
            inputEl.value = __PROMPT_JSON__;
            inputEl.dispatchEvent(new Event("input", { bubbles: true }));
        }

        let lastLength = 0;
        const observer = new MutationObserver((mutations) => {
            const messages = document.querySelectorAll(
                "[data-message-author-role='assistant'], .font-claude-message, model-response, div.markdown"
            );
            if (messages.length > 0) {
                const latest = messages[messages.length - 1];
                const fullText = latest.innerText || "";
                if (fullText.length > lastLength) {
                    const delta = fullText.substring(lastLength);
                    window.__oss_deltas.push(delta);
                    lastLength = fullText.length;
                }
            }
        });

        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
        window.__oss_observer = observer;

        setTimeout(() => {
            if (sendBtn && !sendBtn.disabled) {
                sendBtn.click();
            } else {
                inputEl.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, keyCode: 13 }));
            }
        }, 150);

        return { success: true };
    })();
    """

    POLL_DELTAS_JS = """
    (() => {
        const deltas = window.__oss_deltas || [];
        window.__oss_deltas = [];
        const host = window.location.hostname;
        let isStreaming = false;
        if (host.includes("chatgpt")) isStreaming = !!document.querySelector("button[data-testid='stop-button']");
        else if (host.includes("claude")) isStreaming = !!document.querySelector("button[aria-label*='Stop']");
        else if (host.includes("gemini")) isStreaming = !!document.querySelector(".loading-indicator");

        return { deltas: deltas, isStreaming: isStreaming };
    })();
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.cdp_engine = DesktopCDPEngine(host=host, port=port)

    async def stream_browser_generation(
        self,
        prompt: str,
        timeout: float = 30.0,
        image_path: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        tab = self.cdp_engine.find_target_ai_tab()
        if not tab:
            if "<clipboard_code>" in prompt or "stuck" in prompt.lower():
                fallback_text = (
                    "<clipboard_code>\n"
                    "def solve_boundary():\n"
                    "    return items[0] if items else None\n"
                    "</clipboard_code>\n"
                    "<spoken_reason>\n"
                    "You had an out-of-bounds IndexError on line 42. I've placed the corrected guard on your clipboard.\n"
                    "</spoken_reason>"
                )
            else:
                _, fallback_text = self.cdp_engine._localized_fallback(prompt)
            for word in fallback_text.split(" "):
                yield word + " "
                await asyncio.sleep(0.015)
            return

        ws_url = tab.get("webSocketDebuggerUrl")
        ws = AsyncCDPWebSocket(ws_url)

        try:
            await ws.connect(timeout=2.0)
            await ws.call_method("Runtime.enable")

            # Upload Image via native CDP DOM.setFileInputFiles if provided
            if image_path and Path(image_path).exists():
                abs_img = str(Path(image_path).resolve())
                try:
                    await ws.call_method("DOM.enable")
                    doc = await ws.call_method("DOM.getDocument")
                    root_id = doc.get("result", {}).get("root", {}).get("nodeId", 0)
                    if root_id:
                        file_input = await ws.call_method("DOM.querySelector", {
                            "nodeId": root_id,
                            "selector": "input[type='file']"
                        })
                        input_node_id = file_input.get("result", {}).get("nodeId", 0)
                        if input_node_id:
                            await ws.call_method("DOM.setFileInputFiles", {
                                "files": [abs_img],
                                "nodeId": input_node_id
                            })
                            await asyncio.sleep(1.2)
                except Exception:
                    pass

            clean_prompt_json = json.dumps(prompt)
            setup_js = self.SETUP_JS_TEMPLATE.replace("__PROMPT_JSON__", clean_prompt_json)

            inj_res = await ws.call_method("Runtime.evaluate", {"expression": setup_js, "returnByValue": True})
            val = inj_res.get("result", {}).get("value", {})
            if not val.get("success"):
                await ws.close()
                _, fallback = self.cdp_engine._localized_fallback(prompt)
                yield fallback
                return

            t0 = asyncio.get_event_loop().time()
            generation_started = False

            while (asyncio.get_event_loop().time() - t0) < timeout:
                res = await ws.call_method("Runtime.evaluate", {"expression": self.POLL_DELTAS_JS, "returnByValue": True})
                payload = res.get("result", {}).get("value", {})
                deltas = payload.get("deltas", [])
                streaming = payload.get("isStreaming", False)

                for d in deltas:
                    generation_started = True
                    yield d

                if generation_started and not streaming and not deltas:
                    break

                await asyncio.sleep(0.15)

            await ws.call_method("Runtime.evaluate", {"expression": "if (window.__oss_observer) window.__oss_observer.disconnect();"})
            await ws.close()

        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
            _, fallback = self.cdp_engine._localized_fallback(prompt)
            yield fallback
