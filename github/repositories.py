# github/repositories.py
from typing import List, Dict, Any
from github.client import GitHubClient

class RepositoryManager:
    def __init__(self, client: GitHubClient):
        self.client = client

    def search_repositories(self, query: str = "language:python stars:>500", limit: int = 5) -> List[Dict[str, Any]]:
        endpoint = "/search/repositories"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
        res = self.client.request("GET", endpoint, params=params)
        return res.get("items", [])
