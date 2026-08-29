from llm.router import ModelRouter, AllModelsFailedError
from llm.validators import is_non_empty_code_block
from llm.prompts import SYSTEM_DEBUG_PROMPT
from tools.filesystem import SafeFileSystem
from agent.coding_agent import _extract_code_block


class DebuggingAgent:
    def __init__(self, router: ModelRouter, fs: SafeFileSystem):
        self.router = router
        self.fs = fs

    def attempt_fix(self, file_path: str, test_output: str) -> str:
        try:
            current_content = self.fs.read_file(file_path)
        except FileNotFoundError:
            current_content = "(file does not exist)"

        prompt = (
            f"File: {file_path}\n--- current content ---\n{current_content}\n--- end ---\n\n"
            f"Test failure output:\n{test_output}"
        )
        try:
            res, model_used = self.router.complete_with_fallback(
                "debug",
                [{"role": "system", "content": SYSTEM_DEBUG_PROMPT}, {"role": "user", "content": prompt}],
                validate_fn=is_non_empty_code_block,
            )
            print(f"[DebuggingAgent] {file_path} debug attempt by {model_used}")
        except AllModelsFailedError as e:
            print(f"[DebuggingAgent] debug failed on every model for {file_path}: {e}")
            return current_content

        new_content = _extract_code_block(res)
        self.fs.write_file(file_path, new_content)
        return new_content
