from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

old_snippet = """            code, out = await self.tools.sandbox.execute_and_collect(cli_cmd, timeout=30.0)
            preview = out.strip().splitlines()[-1] if out.strip() else "Completed with no output."
            resp = f"Executed {cli_cmd}. Exit code {code}. {preview}\""""

new_snippet = """            code, out = await self.tools.sandbox.execute_and_collect(cli_cmd, timeout=30.0)
            raw_lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
            valid_lines = [l for l in raw_lines if not l.endswith("$") and not l.endswith("#")]
            preview = " ".join(valid_lines) if valid_lines else (raw_lines[-1] if raw_lines else "Completed with no output.")
            resp = f"Executed {cli_cmd}. Exit code {code}. {preview}\""""

if old_snippet in code:
    code = code.replace(old_snippet, new_snippet)
    target.write_text(code, encoding="utf-8")
    print("[✓] Patched output preview logic in engine_harness.py")
else:
    print("[i] Output preview logic already updated.")
