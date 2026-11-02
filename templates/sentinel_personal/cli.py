import argparse
import json
import os
import re
import sys
import urllib.request
from typing import Any, Dict, List, Optional
from device_controller import EphemeralPersonalAgent

SYSTEM_PROMPT = """You are Sentinel-Personal, a private local Android agent.
ZERO RETENTION: Volatile memory only. All private screen text is structurally stripped.
ACTIONS (JSON only):
{"action": "unlock", "pin": "<PIN>"}
{"action": "launch_app", "package": "<package_name>"}
{"action": "read_notifications"}
{"action": "inspect_screen"}
{"action": "tap_control", "label": "<label>"}
{"action": "tap", "x": <int>, "y": <int>}
{"action": "check_specs", "app_target": "<optional_app_name>"}
{"action": "audit_file", "file_path": "<path_to_file>"}
{"action": "setup_game", "game_name": "mario"}
{"action": "respond", "message": "<msg>"}
"""

class LocalLLMClient:
    def __init__(self, endpoint_url: Optional[str] = None, model: Optional[str] = None):
        self.endpoint_url = endpoint_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1/chat/completions")
        self.model = model or os.environ.get("LOCAL_LLM_MODEL", "llama3.2")

    def query(self, messages: List[Dict[str, str]]) -> str:
        payload = {"model": self.model, "messages": messages, "temperature": 0.1, "stream": False}
        req = urllib.request.Request(self.endpoint_url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1) if "```" in text else m.group(0))
        except Exception:
            pass
    return None

def main():
    parser = argparse.ArgumentParser(description="Sentinel-Personal Standalone Runner")
    parser.add_argument("--adb-host", default="127.0.0.1")
    parser.add_argument("--adb-port", type=int, default=5555)
    args = parser.parse_args()

    agent = EphemeralPersonalAgent(adb_host=args.adb_host, adb_port=args.adb_port)
    llm = LocalLLMClient()
    history = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=" * 55)
    print("      SENTINEL-PERSONAL (STANDALONE AIR-GAPPED)")
    print("=" * 55)
    print("• Retention: Ephemeral RAM-only (No disk logs)")
    print("• Privacy: Structural field allow-listing\n")

    while True:
        try:
            query = input("personal> ").strip()
        except (KeyboardInterrupt, EOFError):
            agent.clear_memory()
            break
        if not query or query.lower() in ("exit", "quit"):
            agent.clear_memory()
            break
        if query.lower() == "clear":
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            agent.clear_memory()
            print("[Memory Cleared]")
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
            elif action == "unlock":
                ok = agent.unlock_device(act.get("pin", ""))
                res = "Device unlocked." if ok else "Unlock failed."
                print(f"[*] {res}\n")
                history.append({"role": "user", "content": f"[Result]: {res}"})
            elif action == "launch_app":
                ok = agent.launch_app(act.get("package", ""))
                res = f"Launched {act.get('package')}." if ok else "Launch failed."
                print(f"[*] {res}\n")
                history.append({"role": "user", "content": f"[Result]: {res}"})
            elif action == "inspect_screen":
                els = agent.get_screen_elements()
                preview = [f"{e['class']} (label: {e['control_label']}, center: {e['center']})" for e in els[:5]]
                summary = f"Found {len(els)} controls:\n" + "\n".join(preview)
                print(f"\n{summary}\n")
                history.append({"role": "user", "content": f"[Result]: {summary}"})
            elif action == "tap_control":
                ok = agent.tap_control(act.get("label", ""))
                res = f"Tapped {act.get('label')}." if ok else "Control not found."
                print(f"[*] {res}\n")
                history.append({"role": "user", "content": f"[Result]: {res}"})
            elif action == "tap":
                ok = agent.tap_coordinates(act.get("x", 0), act.get("y", 0))
                res = f"Tapped ({act.get('x')}, {act.get('y')})." if ok else "Tap failed."
                print(f"[*] {res}\n")
                history.append({"role": "user", "content": f"[Result]: {res}"})
            elif action == "read_notifications":
                notes = agent.get_unread_notifications()
                res = f"Found {len(notes)} notifications."
                print(f"\n{res}\n")
                history.append({"role": "user", "content": f"[Result]: {res}"})
        except Exception as e:
            print(f"[Error] {e}\n")

if __name__ == "__main__":
    main()
