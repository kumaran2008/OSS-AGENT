from pathlib import Path
import re

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Clean up any leftover injected bug from the previous test run
code = code.replace("if int(args.get('line_count', 0)) > 20:\n                    raise IndexError('PA Internal Buffer Limit Exceeded in file_read')\n", "")

# 2. Add exception field to ToolResult dataclass if not present
if "exception: Optional[Exception] = None" not in code:
    code = code.replace(
        "error: Optional[str] = None",
        "error: Optional[str] = None\n    exception: Optional[Exception] = None"
    )

# 3. Add self.last_exception to ToolRegistry.__init__
if "self.last_exception: Optional[Exception] = None" not in code:
    anchor = "self.orchestrator = WorkspaceOrchestrator(self.workspace_root)"
    if anchor in code:
        code = code.replace(anchor, anchor + "\n        self.last_exception: Optional[Exception] = None")

# 4. Record self.last_exception and pass exception=e in dispatch's except block
old_except = "        except Exception as e:\n            return ToolResult(tool_name=tool_name, success=False, error=str(e))"
new_except = """        except Exception as e:
            self.last_exception = e
            return ToolResult(tool_name=tool_name, success=False, error=str(e), exception=e)"""

if old_except in code:
    code = code.replace(old_except, new_except)

target.write_text(code, encoding="utf-8")
print("[✓] Updated tool_registry.py with full exception preservation.")
