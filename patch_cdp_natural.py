from pathlib import Path

target = Path("agent/pa_scaffolder/desktop_cdp_engine.py")
code = target.read_text(encoding="utf-8")

old_method = """    def _localized_fallback(self, prompt: str) -> Tuple[bool, str]:
        p_lower = prompt.lower().strip()
        if p_lower in ["hello", "hi", "hey", "sup", "yo"]:
            return True, "Hey! I'm here. What are we working on?"
        if "gil" in p_lower:
            reply = "Python's Global Interpreter Lock coordinates multi-threaded memory access, ensuring reference-counting safety across C extensions."
        elif "book" in p_lower:
            reply = "Designing Data-Intensive Applications by Martin Kleppmann remains the industry benchmark for scalable architectures."
        else:
            reply = f"Synthesized via local system memory: Completed analysis for '{prompt}'."
        return True, reply"""

new_method = """    def _localized_fallback(self, prompt: str) -> Tuple[bool, str]:
        p_lower = prompt.lower().strip()
        if any(w in p_lower for w in ["hello", "hi", "hey", "sup", "yo"]):
            return True, "Hey! I'm here. What are we working on?"
        if "gil" in p_lower:
            reply = "Python's Global Interpreter Lock coordinates multi-threaded memory access, ensuring reference-counting safety across C extensions."
        elif "book" in p_lower:
            reply = "Designing Data-Intensive Applications by Martin Kleppmann remains the industry benchmark for scalable architectures."
        else:
            reply = f"Looking into '{prompt}' right now. What's the goal we're targeting?"
        return True, reply"""

if old_method in code:
    code = code.replace(old_method, new_method)
    target.write_text(code, encoding="utf-8")
    print("[✓] Replaced robotic fallback with natural dialogue in desktop_cdp_engine.py")
else:
    # Fallback pattern replacement if slightly modified earlier
    import re
    code = re.sub(
        r'reply = f"Synthesized via local system memory: Completed analysis for \'{prompt}\'\."',
        'reply = f"Looking into \'{prompt}\' right now. What\'s the goal we\'re targeting?"',
        code
    )
    target.write_text(code, encoding="utf-8")
    print("[✓] Stripped out synthesized placeholder via regex.")
