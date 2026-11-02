from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

if "self.sandbox = self.pty" not in code:
    anchor = "self.pty = InteractiveSandboxSession(workspace_root=self.workspace_root)"
    code = code.replace(anchor, anchor + "\n        self.sandbox = self.pty")
    target.write_text(code, encoding="utf-8")
    print("[✓] Added self.sandbox alias to ToolRegistry.")
else:
    print("[i] self.sandbox alias already present.")
