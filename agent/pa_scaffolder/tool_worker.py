import sys
import json
import asyncio
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.pa_scaffolder.tool_registry import ToolRegistry


async def run_worker():
    """
    Child process execution entrypoint:
    Reads JSON from stdin: {"tool_name": "...", "tool_args": {...}, "workspace_root": "..."}
    Writes JSON to stdout: {"success": bool, "output": str, "error": str, "traceback": str, ...}
    """
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print(json.dumps({"success": False, "error": "Empty payload received by worker"}))
            return

        payload = json.loads(raw_input)
        tool_name = payload.get("tool_name")
        tool_args = payload.get("tool_args", {})
        ws_root = Path(payload.get("workspace_root", ".")).resolve()

        registry = ToolRegistry(workspace_root=ws_root)
        result = await registry.dispatch(tool_name, tool_args)
        registry.close()

        print(json.dumps({
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "traceback": None,
            "exception_type": None
        }))

    except Exception as exc:
        tb_str = traceback.format_exc()
        # Parse the faulty file and line number from traceback
        tb_lines = tb_str.splitlines()
        faulty_file = None
        faulty_line = None

        for line in reversed(tb_lines):
            if 'File "' in line and '", line ' in line:
                try:
                    parts = line.split('File "')[1].split('", line ')
                    faulty_file = parts[0]
                    faulty_line = int(parts[1].split(",")[0].strip())
                    break
                except Exception:
                    pass

        print(json.dumps({
            "success": False,
            "output": "",
            "error": str(exc),
            "traceback": tb_str,
            "exception_type": type(exc).__name__,
            "faulty_file": faulty_file,
            "faulty_line": faulty_line
        }))


if __name__ == "__main__":
    asyncio.run(run_worker())
