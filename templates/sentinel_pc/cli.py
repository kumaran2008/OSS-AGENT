import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

from filesystem_driver import FilesystemDriver
from local_client import LocalLLMClient
from system_driver import SystemDriver

SENTINEL_PC_PROMPT = """You are Sentinel-PC, a private, local-first PC/Laptop system automation agent.
MANDATES:
- You operate strictly locally. All data stays in process RAM (zero persistent logging).
- Return ONLY a single JSON object corresponding to the requested action.

ACTIONS SCHEMA:
1. Run terminal shell command:
   {"action": "run_shell", "command": "<shell_command>"}
2. Read file:
   {"action": "read_file", "path": "<relative_or_abs_path>"}
3. Write file:
   {"action": "write_file", "path": "<file_path>", "content": "<file_content>"}
4. Search files:
   {"action": "search_files", "pattern": "<glob_pattern>", "subpath": "<optional_subpath>"}
5. List processes:
   {"action": "list_processes", "filter": "<optional_name_filter>"}
6. Check hardware specs:
   {"action": "check_specs"}
7. Respond to user:
   {"action": "respond", "message": "<msg>"}
"""


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1) if "```" in text else m.group(0))
        except Exception:
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Sentinel-PC Local Laptop Runner")
    parser.add_argument("--root", default=".", help="Root workspace directory")
    args = parser.parse_args()

    system_driver = SystemDriver(workspace_root=args.root)
    fs_driver = FilesystemDriver(root_path=args.root)
    llm = LocalLLMClient()

    history: List[Dict[str, str]] = [{"role": "system", "content": SENTINEL_PC_PROMPT}]

    print("=" * 60)
    print("        SENTINEL-PC: LOCAL LAPTOP WORKSTATION AGENT")
    print("=" * 60)
    print("• Retention: Ephemeral RAM-only (No telemetry/cloud logging)")
    print(f"• Root Workspace: {fs_driver.root_path}\n")

    while True:
        try:
            query = input("pc-agent> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nShutting down. Session memory purged.")
            break

        if not query or query.lower() in ("exit", "quit"):
            break
        if query.lower() == "clear":
            history = [{"role": "system", "content": SENTINEL_PC_PROMPT}]
            print("[Context Cleared]\n")
            continue

        history.append({"role": "user", "content": query})

        try:
            raw = llm.query(history)
            act = extract_json(raw)

            if not act or "action" not in act:
                print(f"\n[Agent]: {raw}\n")
                history.append({"role": "assistant", "content": raw})
                continue

            action = act["action"]

            if action == "respond":
                print(f"\n[Agent]: {act.get('message', '')}\n")
                history.append({"role": "assistant", "content": json.dumps(act)})

            elif action == "run_shell":
                cmd = act.get("command", "")
                print(f"[*] Executing shell: {cmd}")
                res = system_driver.run_command(cmd)
                out = res["stdout"] if res["success"] else f"ERR: {res['stderr']}"
                print(f"[*] Output:\n{out}\n")
                history.append({"role": "user", "content": f"[Result]: {out}"})

            elif action == "read_file":
                path = act.get("path", "")
                res = fs_driver.read_file(path)
                out = res.get("content", f"ERR: {res.get('error')}")
                print(f"[*] Read {path} ({len(out)} chars)\n")
                history.append({"role": "user", "content": f"[Result]: {out}"})

            elif action == "write_file":
                path = act.get("path", "")
                content = act.get("content", "")
                res = fs_driver.write_file(path, content)
                out = f"Wrote {res.get('bytes_written')} bytes to {path}" if res["success"] else f"ERR: {res.get('error')}"
                print(f"[*] {out}\n")
                history.append({"role": "user", "content": f"[Result]: {out}"})

            elif action == "search_files":
                pattern = act.get("pattern", "*")
                subpath = act.get("subpath", "")
                matches = fs_driver.search_files(pattern, subpath)
                out = f"Found {len(matches)} matches: " + ", ".join(matches[:10])
                print(f"[*] {out}\n")
                history.append({"role": "user", "content": f"[Result]: {out}"})

            elif action == "list_processes":
                filt = act.get("filter")
                procs = system_driver.list_processes(filt)
                out = f"Active processes: {len(procs)} found"
                print(f"[*] {out}\n")
                history.append({"role": "user", "content": f"[Result]: {procs}"})

            elif action == "check_specs":
                specs = system_driver.get_system_specs()
                out = f"OS: {specs['os']} ({specs['cpu_arch']}) | RAM: {specs['total_ram_mb']}MB | Disk Free: {specs['free_storage_mb']}MB"
                print(f"[*] {out}\n")
                history.append({"role": "user", "content": f"[Result]: {out}"})

        except Exception as e:
            print(f"[Error] {e}\n")


if __name__ == "__main__":
    main()
