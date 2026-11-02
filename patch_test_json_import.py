from pathlib import Path

target = Path("test_researcher_phase1.py")
code = target.read_text(encoding="utf-8")

if "import json" not in code:
    code = "import json\n" + code
    target.write_text(code, encoding="utf-8")
    print("[✓] Added 'import json' to test_researcher_phase1.py")
else:
    print("[i] 'import json' is already present.")
