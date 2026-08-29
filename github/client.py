import requests
from typing import Dict, Any, Optional
from config.settings import settings


class GitHubClient:
    def __init__(self):
        self.base_url = "https://api.github.com"
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if settings.GITHUB_TOKEN:
            self.headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
        self.last_rate_limit: Dict[str, str] = {}

    def request(self, method: str, endpoint: str, params: Optional[Dict] = None,
                data: Optional[Dict] = None) -> Any:
        url = f"{self.base_url}{endpoint}" if not endpoint.startswith("http") else endpoint
        response = requests.request(method, url, headers=self.headers, params=params, json=data, timeout=30)

        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            self.last_rate_limit = {"remaining": remaining, "limit": limit, "reset": reset}
            print(f"[GitHub] rate limit: {remaining}/{limit} remaining")
            if int(remaining) < 5:
                print(f"[GitHub] WARNING — rate limit nearly exhausted ({remaining} left)")

        if response.status_code >= 400:
            raise RuntimeError(f"GitHub API error {response.status_code}: {response.text[:300]}")
        return response.json()

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Explicit check — doesn't consume a search-API-specific quota."""
        return self.request("GET", "/rate_limit")
