import json
import re
from llm.router import ModelRouter, AllModelsFailedError
from llm.validators import is_valid_json_object
from llm.prompts import SYSTEM_REVIEWER_PROMPT
from models.schemas import IssueInfo, ReviewResult


class ReviewerAgent:
    def __init__(self, router: ModelRouter):
        self.router = router

    def review(self, issue: IssueInfo, diff: str) -> ReviewResult:
        prompt = f"Issue: {issue.title}\n{issue.body}\n\n--- git diff ---\n{diff}\n--- end diff ---"
        try:
            res, model_used = self.router.complete_with_fallback(
                "review",
                [{"role": "system", "content": SYSTEM_REVIEWER_PROMPT}, {"role": "user", "content": prompt}],
                validate_fn=is_valid_json_object,
            )
            print(f"[ReviewerAgent] reviewed by {model_used}")
        except AllModelsFailedError as e:
            print(f"[ReviewerAgent] review failed on every model: {e}")
            return ReviewResult(approved=False, feedback=f"Review could not be completed: {e}")

        try:
            match = re.search(r"\{.*\}", res, re.DOTALL)
            data = json.loads(match.group(0) if match else res)
            return ReviewResult(**data)
        except Exception:
            return ReviewResult(approved=False, feedback=f"Could not parse reviewer output:\n{res}")
