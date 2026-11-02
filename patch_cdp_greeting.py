from pathlib import Path

target = Path("agent/pa_scaffolder/desktop_cdp_engine.py")
code = target.read_text(encoding="utf-8")

old_fallback = """    def _localized_fallback(self, prompt: str) -> Tuple[bool, str]:
        p_lower = prompt.lower()
        if "gil" in p_lower:"""

new_fallback = """    def _localized_fallback(self, prompt: str) -> Tuple[bool, str]:
        p_lower = prompt.lower().strip()
        if p_lower in ["hello", "hi", "hey", "sup", "yo"]:
            return True, "Hey! I'm here. What are we working on?"
        if "gil" in p_lower:"""

if old_fallback in code:
    code = code.replace(old_fallback, new_fallback)
    target.write_text(code, encoding="utf-8")
    print("[✓] Patched natural greeting into desktop_cdp_engine.py")
else:
    print("[i] Greeting check already present or target pattern modified.")
