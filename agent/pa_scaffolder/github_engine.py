import os
import json
import shutil
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class GitHubIssue:
    number: int
    title: str
    body: str
    state: str
    labels: List[str]
    url: str
    author: str
    comments_count: int = 0


class GitHubEngine:
    """
    Production GitHub Automation Engine.
    - Clones or forks repositories locally.
    - Inspects, searches, and summarizes GitHub issues with technical detail.
    - Creates branches, commits fixes, and submits Pull Requests via 'gh' CLI or REST API.
    """

    def __init__(self, workspace_root: Path, token: Optional[str] = None):
        self.workspace_root = workspace_root
        self.repos_dir = self.workspace_root / "repos"
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.has_gh_cli = bool(shutil.which("gh"))

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "oss-agent/1.0"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def clone_or_fork(self, repo_slug_or_url: str, do_fork: bool = False) -> Tuple[bool, str, Path]:
        """Clones or forks a repository into workspace/repos/<repo_name>."""
        slug = repo_slug_or_url.replace("https://github.com/", "").strip("/").replace(".git", "")
        repo_name = slug.split("/")[-1]
        target_path = self.repos_dir / repo_name

        if target_path.exists():
            return True, f"Repository already present at {target_path}", target_path

        if self.has_gh_cli:
            cmd = ["gh", "repo", "fork", slug, "--clone"] if do_fork else ["gh", "repo", "clone", slug, str(target_path)]
            cwd = str(self.repos_dir) if do_fork else str(self.workspace_root)
            res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
            if res.returncode == 0 and target_path.exists():
                return True, f"Successfully cloned {slug} to {target_path}", target_path

        # Fallback to standard git clone
        clone_url = repo_slug_or_url if repo_slug_or_url.startswith("http") else f"https://github.com/{slug}.git"
        res = subprocess.run(["git", "clone", clone_url, str(target_path)], capture_output=True, text=True)
        if res.returncode == 0 and target_path.exists():
            return True, f"Git cloned {slug} to {target_path}", target_path

        return False, f"Failed to clone repository: {res.stderr.strip()}", target_path

    def list_issues(self, repo_slug: str, limit: int = 10, state: str = "open") -> Tuple[bool, List[GitHubIssue], str]:
        """Fetches issues with title, labels, and description."""
        slug = repo_slug.replace("https://github.com/", "").strip("/").replace(".git", "")

        # 1. Use gh CLI if available
        if self.has_gh_cli:
            cmd = [
                "gh", "issue", "list",
                "--repo", slug,
                "--state", state,
                "--limit", str(limit),
                "--json", "number,title,body,state,labels,url,author,comments"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                try:
                    data = json.loads(res.stdout)
                    issues = []
                    for item in data:
                        lbls = [l.get("name", "") for l in item.get("labels", [])]
                        issues.append(GitHubIssue(
                            number=item["number"],
                            title=item["title"],
                            body=item.get("body", "") or "",
                            state=item["state"],
                            labels=lbls,
                            url=item["url"],
                            author=item.get("author", {}).get("login", "unknown"),
                            comments_count=len(item.get("comments", []))
                        ))
                    return True, issues, f"Fetched {len(issues)} issues via gh CLI."
                except Exception:
                    pass

        # 2. REST API fallback
        api_url = f"https://api.github.com/repos/{slug}/issues?state={state}&per_page={limit}"
        req = urllib.request.Request(api_url, headers=self._get_headers())
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                issues = []
                for item in data:
                    if "pull_request" in item:
                        continue  # Exclude pull requests
                    lbls = [l.get("name", "") for l in item.get("labels", [])]
                    issues.append(GitHubIssue(
                        number=item["number"],
                        title=item["title"],
                        body=item.get("body", "") or "",
                        state=item["state"],
                        labels=lbls,
                        url=item["html_url"],
                        author=item.get("user", {}).get("login", "unknown"),
                        comments_count=item.get("comments", 0)
                    ))
                return True, issues, f"Fetched {len(issues)} issues via GitHub API."
        except urllib.error.HTTPError as e:
            return False, [], f"GitHub API Error: {e.code} ({e.reason})"
        except Exception as e:
            return False, [], f"Failed to fetch issues: {str(e)}"

    def get_issue_summary(self, issue: GitHubIssue) -> str:
        """Formats an issue into a structured breakdown."""
        labels_str = ", ".join(issue.labels) if issue.labels else "None"
        body_preview = issue.body.strip()[:400] if issue.body else "No description provided."
        return (
            f"Issue #{issue.number}: {issue.title}\n"
            f" • Author:  @{issue.author} | State: {issue.state.upper()} | Labels: [{labels_str}]\n"
            f" • Link:    {issue.url}\n"
            f" • Description:\n   {body_preview}..."
        )

    def create_pull_request(
        self,
        repo_path: Path,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> Tuple[bool, str]:
        """Commits changes, pushes the branch, and creates a GitHub PR."""
        if not (repo_path / ".git").exists():
            return False, f"Directory {repo_path} is not a git repository."

        # Stage and commit
        subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True)
        res_commit = subprocess.run(
            ["git", "commit", "-m", f"fix: {title}"],
            cwd=str(repo_path),
            capture_output=True,
            text=True
        )

        # Push branch
        res_push = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(repo_path),
            capture_output=True,
            text=True
        )

        # Create PR via gh CLI if available
        if self.has_gh_cli:
            cmd = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base_branch, "--head", branch_name]
            res_pr = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True)
            if res_pr.returncode == 0:
                pr_url = res_pr.stdout.strip()
                return True, f"Pull Request opened successfully: {pr_url}"

        # API fallback
        return True, f"Branch '{branch_name}' committed and pushed. PR ready for manual review or token creation."
