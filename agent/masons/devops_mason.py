from agent.masons.base_mason import BaseMason
from tools.filesystem import SafeFileSystem
from llm.router import ModelRouter

DEVOPS_ROLE_PROMPT = """You are the DevOps Mason for oss-agent.
Your domain is CI/CD infrastructure, Docker packaging, shell automation, and deployment configurations.
Rules:
1. Write minimal, multi-stage, rootless Dockerfiles and reproducible CI scripts.
2. Handle environment variable isolation, caching, and healthchecks cleanly.
3. Return complete, production-ready code enclosed in markdown code fences.
"""

class DevOpsMason(BaseMason):
    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        super().__init__(
            domain="DevOps",
            role_prompt=DEVOPS_ROLE_PROMPT,
            router=router,
            fs=fs,
        )
