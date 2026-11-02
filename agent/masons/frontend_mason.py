from agent.masons.base_mason import BaseMason
from tools.filesystem import SafeFileSystem
from llm.router import ModelRouter

FRONTEND_ROLE_PROMPT = """You are the Frontend Mason for oss-agent.
Your domain is client-side architecture, modern TypeScript/JavaScript, CSS, and UI state management.
Rules:
1. Write clean, modular, accessible, and standards-compliant web code.
2. Enforce clean component boundaries and state separation.
3. Return complete, production-ready code enclosed in markdown code fences.
"""

class FrontendMason(BaseMason):
    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        super().__init__(
            domain="Frontend",
            role_prompt=FRONTEND_ROLE_PROMPT,
            router=router,
            fs=fs,
        )
