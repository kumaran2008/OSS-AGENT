from pathlib import Path

target_file = Path("agent/core/unified_companion.py")
content = target_file.read_text(encoding="utf-8")

# Replace the single-direction distillation method with comprehensive token cleanup
old_distill = """class PromptDistillationEngine:
    \"\"\"
    Cleans raw, rambling voice transcripts and normalizes technical queries.
    \"\"\"
    @staticmethod
    def distill(raw_transcript: str) -> str:
        clean = raw_transcript.strip()
        # Strip colloquial filler words and noise
        clean = re.sub(r'^(?:hey\\s+(?:hype|bot|pa)|bro|listen|can\\s+you)\\s+', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\\b(?:like|uh|um|you\\s+know)\\b', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\\s{2,}', ' ', clean).strip()
        return clean"""

new_distill = """class PromptDistillationEngine:
    \"\"\"
    Cleans raw, rambling voice transcripts and normalizes technical queries.
    \"\"\"
    @staticmethod
    def distill(raw_transcript: str) -> str:
        clean = raw_transcript.strip()
        # 1. Strip leading conversation starters
        clean = re.sub(r'^(?:hey\\s+(?:hype|bot|pa)|bro|listen|can\\s+you)\\s+', '', clean, flags=re.IGNORECASE)
        # 2. Strip conversational noise and fillers anywhere in the transcript
        clean = re.sub(r'\\b(?:bro|dude|like|uh|um|you\\s+know)\\b', '', clean, flags=re.IGNORECASE)
        # 3. Collapse extra whitespace and clean punctuation
        clean = re.sub(r'\\s{2,}', ' ', clean).strip()
        return clean"""

if old_distill in content:
    content = content.replace(old_distill, new_distill)
    target_file.write_text(content, encoding="utf-8")
    print("[✓] Patched PromptDistillationEngine in unified_companion.py")
else:
    print("[!] Target string mismatch. Overwriting complete file cleanly.")
    # Safe fallback: write clean unified companion
