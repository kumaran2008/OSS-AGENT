# github/forks.py
from typing import Dict, Any
from github.client import GitHubClient

class ForkManager:
    def __init__(self, client: GitHubClient):
        self.client = client

    def create_fork(self, repo_full_name: str) -> Dict[str, Any]:
        endpoint = f"/repos/{repo_full_name}/forks"
        return self.client.request("POST", endpoint)
