from pathlib import Path
import re

target = Path("agent/pa_scaffolder/pty_sandbox.py")
code = target.read_text(encoding="utf-8")

if "import asyncio" not in code:
    code = "import asyncio\n" + code

if "def execute_and_collect" not in code:
    async_method = """    async def execute_and_collect(self, command: str, timeout: float = 30.0) -> Tuple[int, str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.execute_command, command, timeout)
"""
    code = re.sub(r'(class InteractiveSandboxSession[^\n]*:\n)', r'\1' + async_method + '\n', code, count=1)
    target.write_text(code, encoding="utf-8")
    print("[✓] Added execute_and_collect to InteractiveSandboxSession.")
else:
    print("[i] execute_and_collect already present in InteractiveSandboxSession.")
