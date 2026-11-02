import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from agent.pa_scaffolder.platform_adapter import PlatformAdapter, DeviceTier
from agent.pa_scaffolder.desktop_cdp_engine import DesktopCDPEngine


class UnifiedBrowserController:
    """
    Production-grade adaptive browser controller:
    - Desktop/Laptop: Native Playwright (Chromium/Firefox/WebKit) with full locator support.
    - Mobile/Termux: Native WebSocket Chrome DevTools Protocol (CDP).
    - Exposes a unified async API for navigation, DOM extraction, JS evaluation, and clicks.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.profile = PlatformAdapter.detect_hardware()
        self.cdp_engine = DesktopCDPEngine()
        self._playwright = None
        self._browser = None
        self._page = None
        self._backend = "cdp"  # Default fallback

    async def _init_backend(self):
        """Initializes Playwright if running on laptop/desktop/server, else uses CDP."""
        if self._page is not None:
            return

        if self.profile.tier in [DeviceTier.MEDIUM_LAPTOP, DeviceTier.HIGH_DESKTOP, DeviceTier.ENTERPRISE_SERVER]:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                self._page = await self._browser.new_page()
                self._backend = "playwright"
                return
            except Exception:
                # Playwright not installed or missing browser binaries; fall back to CDP
                pass

        self._backend = "cdp"

    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigates to URL and waits for network idle."""
        await self._init_backend()

        if self._backend == "playwright" and self._page:
            try:
                resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=25000)
                status = resp.status if resp else 200
                title = await self._page.title()
                return {
                    "success": True,
                    "backend": "playwright",
                    "url": self._page.url,
                    "status_code": status,
                    "title": title
                }
            except Exception as e:
                return {"success": False, "backend": "playwright", "error": str(e)}

        # CDP Fallback
        res = await self.cdp_engine.navigate(url)
        return {"success": True, "backend": "cdp", "response": res}

    async def extract_text(self, selector: str = "body") -> str:
        """Extracts text content from a DOM selector."""
        await self._init_backend()

        if self._backend == "playwright" and self._page:
            try:
                locator = self._page.locator(selector)
                if await locator.count() > 0:
                    text = await locator.first.inner_text()
                    return text.strip() if text else "(Element has no text)"
                return f"Selector '{selector}' not found on page."
            except Exception as e:
                return f"Playwright extraction error: {e}"

        # CDP Fallback (escaped curly braces)
        js = (
            "(function() { "
            "  var el = document.querySelector('" + selector.replace("'", "\\'") + "'); "
            "  return el ? (el.innerText || el.textContent) : 'Element not found'; "
            "})()"
        )
        res = await self.cdp_engine.evaluate_js(js)
        return str(res.get("value", res) if isinstance(res, dict) else res)

    async def evaluate_js(self, script: str) -> Any:
        """Evaluates arbitrary JavaScript in the page context."""
        await self._init_backend()

        if self._backend == "playwright" and self._page:
            try:
                val = await self._page.evaluate(script)
                return val
            except Exception as e:
                return f"Playwright JS execution error: {e}"

        # CDP Fallback
        res = await self.cdp_engine.evaluate_js(script)
        return res.get("value", res) if isinstance(res, dict) else res

    async def click_selector(self, selector: str) -> str:
        """Clicks an element matching the selector."""
        await self._init_backend()

        if self._backend == "playwright" and self._page:
            try:
                locator = self._page.locator(selector)
                if await locator.count() > 0:
                    await locator.first.click(timeout=5000)
                    return f"Clicked '{selector}' via Playwright."
                return f"Element '{selector}' not found to click."
            except Exception as e:
                return f"Playwright click error: {e}"

        # CDP Fallback
        js = (
            "(function() { "
            "  var el = document.querySelector('" + selector.replace("'", "\\'") + "'); "
            "  if (el) { el.click(); return 'Clicked ' + el.tagName; } "
            "  return 'Element not found'; "
            "})()"
        )
        res = await self.cdp_engine.evaluate_js(js)
        val = str(res.get("value", res) if isinstance(res, dict) else res)
        return val

    async def capture_screenshot(self, output_path: str) -> str:
        """Captures page screenshot to disk."""
        await self._init_backend()
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        if self._backend == "playwright" and self._page:
            try:
                await self._page.screenshot(path=str(out), full_page=False)
                return f"Screenshot saved to {out} via Playwright."
            except Exception as e:
                return f"Playwright screenshot error: {e}"

        # CDP Screenshot Fallback
        try:
            res = await self.cdp_engine.capture_screenshot()
            b64_data = res.get("data") if isinstance(res, dict) else None
            if b64_data:
                import base64
                out.write_bytes(base64.b64decode(b64_data))
                return f"Screenshot saved to {out} via CDP."
            return "CDP did not return image data."
        except Exception as e:
            return f"CDP screenshot error: {e}"

    async def close(self):
        """Cleans up browser instances."""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._page = None
        self._browser = None
        self._playwright = None
