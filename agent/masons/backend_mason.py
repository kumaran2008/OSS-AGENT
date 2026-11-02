from agent.masons.base_mason import BaseMason
from tools.filesystem import SafeFileSystem
from llm.router import ModelRouter

BACKEND_ROLE_PROMPT = """You are the Backend Mason for oss-agent.
Your domain is robust Python service architectures, REST/FastAPI endpoints, database queries, and async pipelines.
Rules:
1. Write typed, PEP 8 compliant, exception-safe code with clear error handling.
2. Minimize external dependencies; leverage Python standard libraries where possible.
3. Return complete, production-ready code enclosed in markdown code fences.
"""

class BackendMason(BaseMason):
    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        super().__init__(
            domain="Backend",
            role_prompt=BACKEND_ROLE_PROMPT,
            router=router,
            fs=fs,
        )
