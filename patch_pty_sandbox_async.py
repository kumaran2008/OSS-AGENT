from pathlib import Path

target = Path("agent/pa_scaffolder/pty_sandbox.py")
code = target.read_text(encoding="utf-8")

if "import asyncio" not in code:
    code = "import asyncio\n" + code

async_method = """    async def execute_and_collect(self, command: str, timeout: float = 30.0) -> Tuple[int, str]:
        \"\"\"Asynchronous wrapper around execute_command.\"\"\"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.execute_command, command, timeout)
"""

if "def execute_and_collect" not in code:
    anchor = "    def execute_command("
    code = code.replace(anchor, async_method + "\n" + anchor)

target.write_text(code, encoding="utf-8")
print("[✓] Added execute_and_collect to InteractiveSandboxSession.")
