from typing import List, Dict, Any, Optional
from github.client import GitHubClient
from github.forks import ForkManager as _ForkManager
from github.issues import IssueManager as _IssueManager
from github.pull_requests import PullRequestManager as _PullRequestManager
from github.repositories import RepositoryManager as _RepositoryManager
from models.schemas import RepositoryInfo, IssueInfo


class ForkManager(_ForkManager):
    def __init__(self, client: Optional[GitHubClient] = None):
        super().__init__(client or GitHubClient())


class PullRequestManager(_PullRequestManager):
    def __init__(self, client: Optional[GitHubClient] = None):
        super().__init__(client or GitHubClient())


class RepositoryManager(_RepositoryManager):
    def __init__(self, client: Optional[GitHubClient] = None):
        super().__init__(client or GitHubClient())


class IssueSelector(_IssueManager):
    """
    Convenience wrapper around the real github.issues.IssueManager,
    adding repo-lookup and raw-issue-fetch helpers. Subclasses the real,
    verified package rather than reimplementing it, so this stays in
    sync with any future changes to github/issues.py.
    """

    def __init__(self, client: Optional[GitHubClient] = None):
        self.client = client or GitHubClient()
        super().__init__(self.client)

    def _dict_to_repo_info(self, data: Dict[str, Any]) -> RepositoryInfo:
        owner_name = data.get("owner", {}).get("login", "") if isinstance(data.get("owner"), dict) else ""
        return RepositoryInfo(
            owner=owner_name,
            name=data.get("name", ""),
            full_name=data.get("full_name", ""),
            clone_url=data.get("clone_url", ""),
            ssh_url=data.get("ssh_url", ""),
            default_branch=data.get("default_branch", "main"),
            description=data.get("description") or "",
            stargazers_count=data.get("stargazers_count", 0),
            language=data.get("language") or "",
        )

    def get_repo_info(self, repo_full_name: str) -> RepositoryInfo:
        data = self.client.request("GET", f"/repos/{repo_full_name}")
        return self._dict_to_repo_info(data)

    def find_best_repo(self, query: Optional[str] = None) -> Optional[RepositoryInfo]:
        search_q = query or "language:python stars:>500"
        endpoint = "/search/repositories"
        params = {"q": search_q, "sort": "stars", "order": "desc", "per_page": 5}
        res = self.client.request("GET", endpoint, params=params)
        items = res.get("items", [])
        if not items:
            return None
        return self._dict_to_repo_info(items[0])

    def get_issue(self, repo_full_name: str, issue_number: int) -> Dict[str, Any]:
        """Returns the raw GitHub API issue payload — matches how
        agent/orchestrator.py already handles direct issue fetches
        elsewhere, converting to IssueInfo at the call site rather than
        here, so there's one consistent conversion path in the codebase."""
        return self.client.request("GET", f"/repos/{repo_full_name}/issues/{issue_number}")

    def get_issue_info(self, repo_full_name: str, issue_number: int) -> IssueInfo:
        """Same as get_issue(), but returns a converted IssueInfo object
        for callers that want the typed model directly."""
        data = self.get_issue(repo_full_name, issue_number)
        return IssueInfo(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body") or "",
            html_url=data.get("html_url", ""),
            repository_full_name=repo_full_name,
            labels=[l.get("name", "") for l in data.get("labels", []) if isinstance(l, dict)],
        )

    def list_open_issues(self, repo_full_name: str) -> List[Dict[str, Any]]:
        return self.search_issues(repo_full_name, state="open", limit=10)


__all__ = ["ForkManager", "PullRequestManager", "IssueSelector", "RepositoryManager", "GitHubClient"]
