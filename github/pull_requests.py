# github/pull_requests.py
from typing import Dict, Any
from github.client import GitHubClient

class PullRequestManager:
    def __init__(self, client: GitHubClient):
        self.client = client

    def create_pull_request(self, repo_full_name: str, title: str, head: str, base: str, body: str) -> Dict[str, Any]:
        endpoint = f"/repos/{repo_full_name}/pulls"
        payload = {"title": title, "head": head, "base": base, "body": body}
        return self.client.request("POST", endpoint, data=payload)
