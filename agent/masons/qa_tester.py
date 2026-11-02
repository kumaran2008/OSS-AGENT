from agent.masons.base_mason import BaseMason
from tools.filesystem import SafeFileSystem
from llm.router import ModelRouter

QA_ROLE_PROMPT = """You are the QA Tester Mason for oss-agent.
Your domain is writing test suites using pytest and standard unit testing frameworks.
Rules:
1. Maximize branch coverage, test realistic failure modes, and mock external IO.
2. Structure tests with clear arrange-act-assert boundaries.
3. Return complete, runnable test code enclosed in markdown code fences.
"""

class QATesterMason(BaseMason):
    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        super().__init__(
            domain="QATester",
            role_prompt=QA_ROLE_PROMPT,
            router=router,
            fs=fs,
        )
