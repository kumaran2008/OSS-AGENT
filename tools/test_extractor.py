import ast
import re
from pathlib import Path
from typing import Optional

class DeterministicTestExtractor:
    """
    Extracts executable reproduction snippets from issue descriptions,
    validates syntax safely across all tiers, and builds an isolated test fixture.
    """

    CODE_BLOCK_PATTERN = re.compile(r"```(?:python|py)?\n(.*?)```", re.DOTALL | re.IGNORECASE)

    def extract_reproduction_code(self, issue_body: str) -> Optional[str]:
        if not issue_body:
            return None

        blocks = self.CODE_BLOCK_PATTERN.findall(issue_body)
        if not blocks:
            return None

        viable_blocks = []
        for block in blocks:
            b = block.strip()
            # Ignore command-line or traceback snippets
            if b.startswith(("$", "git", "diff", "Traceback", "npm", "pip")):
                continue

            # Verify snippet contains real logic
            if any(k in b for k in ("import ", "assert ", "def ", "==", "(")):
                # Strictly validate syntax so broken code blocks are discarded
                if self._is_valid_python_syntax(b):
                    viable_blocks.append(b)

        if not viable_blocks:
            return None

        # Prioritize blocks containing assertions
        viable_blocks.sort(key=lambda x: ("assert" in x or "def test" in x), reverse=True)
        return viable_blocks[0]

    def _is_valid_python_syntax(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except (SyntaxError, ValueError):
            return False

    def create_reproduction_fixture(self, repo_dir: Path, issue_body: str) -> Optional[Path]:
        code = self.extract_reproduction_code(issue_body)
        if not code:
            return None

        fixture_dir = repo_dir / "tests_ossagent_repro"
        fixture_dir.mkdir(exist_ok=True)
        fixture_file = fixture_dir / "test_reproduce_issue.py"

        wrapper = [
            "# Auto-generated reproduction fixture by OSS-Agent",
            "import sys",
            "from pathlib import Path",
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))",
            "",
            "def test_issue_reproduction():",
        ]

        for line in code.splitlines():
            wrapper.append(f"    {line}")

        wrapper.append("")

        fixture_file.write_text("\n".join(wrapper), encoding="utf-8")
        return fixture_file
