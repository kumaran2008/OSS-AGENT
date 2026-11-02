import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.personal.sentinel_device import EphemeralPersonalAgent

SENTINEL_SYSTEM_PROMPT = """You are Sentinel-Personal, a private local Android automation agent.
ZERO-RETENTION MANDATE:
- All data resides strictly in volatile memory. No disk writes to training buffers or logs.
- You operate over STRUCTURALLY SANITIZED elements. Private user text is stripped.

AVAILABLE ACTIONS (JSON object only):
1. Unlock phone:
   {"action": "unlock", "pin": "<PIN>"}
2. Launch app:
   {"action": "launch_app", "package": "<package_name>", "activity": "<optional>"}
3. Check notifications:
   {"action": "read_notifications"}
4. Inspect interactive screen buttons:
   {"action": "inspect_screen"}
5. Tap recognized control button:
   {"action": "tap_control", "label": "<control_label>"}
6. Tap coordinates:
   {"action": "tap", "x": <int>, "y": <int>}
7. Respond to user:
   {"action": "respond", "message": "<your_message>"}

Return ONLY a single valid JSON object.
"""


class LocalLLMClient:
    def __init__(self, endpoint_url: Optional[str] = None, model: Optional[str] = None):
        self.endpoint_url = endpoint_url or os.environ.get(
            "LOCAL_LLM_URL", "http://localhost:11434/v1/chat/completions"
        )
        self.model = model or os.environ.get("LOCAL_LLM_MODEL", "llama3.2")

    def query(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
            "stream": False,
        }
        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()


def extract_json_action(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        obj_match = re.search(r"\{.*?\}", text, re.DOTALL)
        if obj_match:
            text = obj_match.group(0)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_interactive_cli(adb_host: str = "127.0.0.1", adb_port: int = 5555):
    print("=" * 60)
    print("     SENTINEL-PERSONAL: STRUCTURALLY ISOLATED CLI")
    print("=" * 60)
    print("• Retention: Ephemeral RAM-only")
    print("• Privacy: Structural field allow-listing (No raw text leak)")
    print("=" * 60 + "\n")

    agent = EphemeralPersonalAgent(adb_host=adb_host, adb_port=adb_port)
    llm = LocalLLMClient()
    chat_history: List[Dict[str, str]] = [{"role": "system", "content": SENTINEL_SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("personal-agent> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nPurging session. Exiting.")
            agent.clear_memory()
            break

        if not user_input or user_input.lower() in ("exit", "quit"):
            agent.clear_memory()
            break
        if user_input.lower() == "clear":
            chat_history = [{"role": "system", "content": SENTINEL_SYSTEM_PROMPT}]
            agent.clear_memory()
            print("[Sentinel] Memory purged.\n")
            continue

        chat_history.append({"role": "user", "content": user_input})

        try:
            raw_response = llm.query(chat_history)
            action_data = extract_json_action(raw_response)

            if not action_data or "action" not in action_data:
                print(f"\n[Agent]: {raw_response}\n")
                chat_history.append({"role": "assistant", "content": raw_response})
                continue

            action = action_data.get("action")

            if action == "respond":
                msg = action_data.get("message", "")
                print(f"\n[Agent]: {msg}\n")
                chat_history.append({"role": "assistant", "content": json.dumps(action_data)})

            elif action == "unlock":
                pin = action_data.get("pin", "")
                print(f"[*] Unlocking device (PIN: {'*' * len(pin)})...")
                ok = agent.unlock_device(pin)
                res = "Device unlocked." if ok else "Unlock failed."
                print(f"[*] {res}\n")
                chat_history.append({"role": "user", "content": f"[Result]: {res}"})

            elif action == "launch_app":
                pkg = action_data.get("package", "")
                ok = agent.launch_app(pkg, action_data.get("activity"))
                res = f"Launched {pkg}." if ok else f"Failed to launch {pkg}."
                print(f"[*] {res}\n")
                chat_history.append({"role": "user", "content": f"[Result]: {res}"})

            elif action == "inspect_screen":
                elements = agent.get_screen_elements()
                preview = [f"{e['class']} (label: {e['control_label']}, center: {e['center']})" for e in elements[:6]]
                summary = f"Interactive Elements ({len(elements)} found):\n" + "\n".join(preview)
                print(f"\n{summary}\n")
                chat_history.append({"role": "user", "content": f"[Result]: {summary}"})

            elif action == "tap_control":
                lbl = action_data.get("label", "")
                ok = agent.tap_element_by_control(lbl)
                res = f"Tapped control '{lbl}'." if ok else f"Control '{lbl}' not found on screen."
                print(f"[*] {res}\n")
                chat_history.append({"role": "user", "content": f"[Result]: {res}"})

            elif action == "tap":
                x, y = action_data.get("x", 0), action_data.get("y", 0)
                ok = agent.tap_coordinates(x, y)
                res = f"Tapped ({x}, {y})." if ok else f"Failed to tap ({x}, {y})."
                print(f"[*] {res}\n")
                chat_history.append({"role": "user", "content": f"[Result]: {res}"})

            elif action == "read_notifications":
                notes = agent.get_unread_notifications()
                summary = f"Active Notifications: {len(notes)} item(s) found across packages: " + ", ".join(
                    {n.get("packageName", "unknown") for n in notes}
                )
                print(f"\n{summary}\n")
                chat_history.append({"role": "user", "content": f"[Result]: {summary}"})

        except Exception as e:
            print(f"\n[Error] {e}\n")


def main():
    parser = argparse.ArgumentParser(description="Sentinel-Personal CLI")
    parser.add_argument("--adb-host", default="127.0.0.1")
    parser.add_argument("--adb-port", type=int, default=5555)
    args = parser.parse_args()
    run_interactive_cli(adb_host=args.adb_host, adb_port=args.adb_port)


if __name__ == "__main__":
    main()
