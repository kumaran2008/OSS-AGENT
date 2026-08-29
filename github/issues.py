from typing import List, Dict, Any
from github.client import GitHubClient


class IssueManager:
    def __init__(self, client: GitHubClient):
        self.client = client

    def search_issues(self, repo_full_name: str, state: str = "open", limit: int = 5) -> List[Dict[str, Any]]:
        endpoint = f"/repos/{repo_full_name}/issues"

        params = {"state": state, "per_page": limit, "labels": "good first issue"}
        try:
            items = self.client.request("GET", endpoint, params=params)
        except Exception:
            items = []

        items = [item for item in items if "pull_request" not in item]

        # Fall back to all open issues if the "good first issue" label
        # search returned nothing (not just on error, but on empty result).
        if not items:
            params.pop("labels", None)
            try:
                items = self.client.request("GET", endpoint, params=params)
            except Exception:
                items = []
            items = [item for item in items if "pull_request" not in item]

        return items
