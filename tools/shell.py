import os
import subprocess
from pathlib import Path
from typing import Tuple
from config.settings import settings

DANGEROUS_PATTERNS = [
    "rm -rf", "rm  -rf", "rm -fr", "sudo", "chmod 777", "chmod -r 777",
    "curl ", "wget ", "mkfs", "> /dev/", "dd if=", ".ssh",
    "curl | sh", "wget | sh", "| sh", "| bash", "| zsh",
    "eval ", "exec(", "base64 -d", "base64 --decode",
    "/etc/passwd", "/etc/shadow", "authorized_keys",
    "printenv", "env |", "export -p",
    ":(){:|:&};:",  # fork bomb
]

SECRET_ENV_KEYS = ["OPENROUTER_API_KEY", "GITHUB_TOKEN"]


class SafeShell:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def execute(self, command: str, auto_approve_override: bool = False) -> Tuple[int, str, str]:
        lowered = command.lower()
        for pattern in DANGEROUS_PATTERNS:
            if pattern.lower() in lowered:
                raise ValueError(f"Command blocked — matches dangerous pattern: '{pattern}'")

        if ".." in command:
            raise ValueError("Command blocked — contains path traversal ('..').")

        print(f"\n[SHELL COMMAND PROPOSAL]\n  cwd: {self.workspace_root}\n  cmd: {command}\n")

        if not (settings.AUTO_APPROVE_COMMANDS or auto_approve_override):
            choice = input("Execute this command? [y/N]: ").strip().lower()
            if choice != "y":
                return -1, "", "Execution cancelled by user."

        clean_env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV_KEYS}

        process = subprocess.Popen(
            command, shell=True, cwd=self.workspace_root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=clean_env,
        )
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr
