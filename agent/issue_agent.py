from llm.router import ModelRouter, AllModelsFailedError
from models.schemas import IssueInfo


class IssueAgent:
    def __init__(self, router: ModelRouter):
        self.router = router

    def rank_and_select(self, issues: list) -> IssueInfo:
        if not issues:
            raise ValueError("No issues to select from.")
        summaries = "\n".join(f"[{i}] #{it['number']}: {it['title']}" for i, it in enumerate(issues))
        prompt = (f"Pick the single most tractable issue for an automated fix.\n{summaries}\n"
                  f"Reply with only the index number.")
        try:
            res, model_used = self.router.complete_with_fallback(
                "analysis",
                [{"role": "user", "content": prompt}],
            )
            print(f"[IssueAgent] ranked by {model_used}")
        except AllModelsFailedError:
            res = "0"  # fall back to the first issue if every model fails

        try:
            idx = int("".join(c for c in res if c.isdigit()) or "0")
            idx = idx if 0 <= idx < len(issues) else 0
        except Exception:
            idx = 0

        chosen = issues[idx]
        return IssueInfo(
            number=chosen["number"],
            title=chosen["title"],
            body=chosen.get("body", "") or "",
            html_url=chosen["html_url"],
            repository_full_name=chosen["repository_url"].split("/repos/")[-1],
            labels=[l["name"] for l in chosen.get("labels", [])],
        )
