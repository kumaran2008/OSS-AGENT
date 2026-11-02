from pathlib import Path
from llm.router import ModelRouter
from tools.filesystem import SafeFileSystem
from agent.masons.base_mason import BaseMason

CONFIG_ROLE_PROMPT = (
    "You are a DevOps & Tooling Specialist. Build valid configuration manifests "
    "(package.json, requirements.txt, configs, Dockerfiles). Ensure dependency pins and environments are clean."
)

class ConfigMason(BaseMason):
    """Specialist responsible for dependencies, deployment configurations, and project manifests."""

    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        super().__init__(
            domain="Config Mason",
            role_prompt=CONFIG_ROLE_PROMPT,
            router=router,
            fs=fs,
        )

    @staticmethod
    def can_handle(file_path: str) -> bool:
        name = Path(file_path).name.lower()
        return name in [
            "package.json",
            "requirements.txt",
            "dockerfile",
            ".env.example",
            "cargo.toml",
            "setup.py",
            "pyproject.toml",
        ]
