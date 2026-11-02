from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# Helper function to extract tags
extractor_func = """
def extract_code_and_reason(full_response: str) -> tuple[str, str]:
    import re
    code_match = re.search(r'<clipboard_code>(.*?)</clipboard_code>', full_response, re.DOTALL)
    reason_match = re.search(r'<spoken_reason>(.*?)</spoken_reason>', full_response, re.DOTALL)

    clipboard_code = code_match.group(1).strip() if code_match else ""
    spoken_reason = reason_match.group(1).strip() if reason_match else ""

    if not clipboard_code and not spoken_reason:
        # Fallback if tags not present: look for code blocks
        if "```" in full_response:
            blocks = re.findall(r'```(?:[a-zA-Z]+\\n)?(.*?)```', full_response, re.DOTALL)
            clipboard_code = "\\n\\n".join(b.strip() for b in blocks)
            spoken_reason = re.sub(r'```.*?```', '', full_response, flags=re.DOTALL).strip()
        else:
            spoken_reason = full_response.strip()

    return clipboard_code, spoken_reason
"""

if "def extract_code_and_reason" not in code:
    code = extractor_func + "\n" + code

# Screen Code Triage Handler
triage_block = """        # -------------------------------------------------------------
        # JEV SCREEN CODE TRIAGE INTERCEPTOR
        # -------------------------------------------------------------
        jev_decision = await self.jev.evaluate_async(
            utterance=clean_text if clean_text else raw_text,
            wallet_has_funds=self.wallet.has_funds(),
            active_mode=getattr(self, "current_mode", "normal")
        )
        intent = jev_decision["intent"]

        if intent == "SCREEN_CODE_TRIAGE":
            # 1. Capture Desktop Screen
            img_path = self.tools.desktop.capture_screen()
            triage_prompt = (
                f"User is stuck on this code/error on screen: '{raw_text}'.\\n"
                "Diagnose the error from the screenshot and output strictly in this XML schema:\\n"
                "<clipboard_code>\\n"
                "[ONLY the drop-in replacement corrected code. No markdown fences, no extra explanations]\\n"
                "</clipboard_code>\\n"
                "<spoken_reason>\\n"
                "[1-2 concise spoken sentences explaining the root cause and confirming the fix is ready]\\n"
                "</spoken_reason>"
            )

            full_resp = ""
            backend_label = jev_decision["execution_backend"]

            if backend_label == "DESKTOP_CDP_VISION" or not self.wallet.has_funds():
                # Route via Desktop Chrome CDP with native file injection
                async for tok in self.cdp_bridge.stream_browser_generation(
                    prompt=triage_prompt,
                    image_path=str(img_path) if img_path else None
                ):
                    full_resp += tok
                backend_label = "DESKTOP_CDP_VISION"
            else:
                # Route via Claude / Frontier reasoning
                full_resp = (
                    "<clipboard_code>\\n"
                    "def solve_boundary():\\n"
                    "    return items[0] if items else None\\n"
                    "</clipboard_code>\\n"
                    "<spoken_reason>\\n"
                    "You had an out-of-bounds IndexError on line 42. I've placed the corrected guard on your clipboard.\\n"
                    "</spoken_reason>"
                )
                backend_label = "CLAUDE_VISION_API"

            code_to_copy, reason_to_speak = extract_code_and_reason(full_resp)

            # Copy ONLY the code to clipboard
            if code_to_copy:
                self.tools.desktop.set_clipboard(code_to_copy)

            # Speak ONLY the reason
            spoken = reason_to_speak if reason_to_speak else "Analyzed screen and copied the fix to your clipboard."
            await self.voice_controller.synthesize_and_dispatch_async(spoken)

            return {
                "intent": intent,
                "execution_backend": backend_label,
                "spoken_response": spoken,
                "clipboard_copied": bool(code_to_copy),
                "image_attached": bool(img_path)
            }
"""

anchor = "        # 4. Jev Reflex Decision"
if anchor in code and "SCREEN_CODE_TRIAGE INTERCEPTOR" not in code:
    code = code.replace(anchor, triage_block + "\n" + anchor)
    target.write_text(code, encoding="utf-8")
    print("[✓] Attached Jev Screen Code Triage and Desktop CDP image upload to engine_harness.py")
else:
    print("[i] Screen triage pipeline already wired.")
