import re
from pathlib import Path

target = Path("agent/pa_scaffolder/wallet.py")
code = target.read_text(encoding="utf-8")

if "@balance.setter" not in code:
    # Match the getter property
    getter_pattern = re.compile(r'(@property\s+def balance\(self\)[^:]*:\s+.*?return\s+(self\.\w+))', re.DOTALL)
    match = getter_pattern.search(code)
    if match:
        getter_str = match.group(1)
        var_name = match.group(2)
        setter_str = f"""

    @balance.setter
    def balance(self, value: float):
        {var_name} = float(value)"""
        code = code.replace(getter_str, getter_str + setter_str)
        target.write_text(code, encoding="utf-8")
        print(f"[✓] Added @balance.setter targeting {var_name} in wallet.py")
    else:
        setter_fallback = """
    @balance.setter
    def balance(self, value: float):
        if hasattr(self, "_balance"):
            self._balance = float(value)
        elif hasattr(self, "current_balance"):
            self.current_balance = float(value)
        else:
            self._balance = float(value)
"""
        code += "\n" + setter_fallback
        target.write_text(code, encoding="utf-8")
        print("[✓] Appended fallback @balance.setter to wallet.py")
else:
    print("[i] @balance.setter already present in wallet.py")
