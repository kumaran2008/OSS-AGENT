import random
import time
from pathlib import Path
from config.settings import settings
from models.schemas import RepositoryInfo
from github.client import GitHubClient
from github.repositories import RepositoryManager
from github.issues import IssueManager
from github.forks import ForkManager
from github.pull_requests import PullRequestManager
from llm.router import ModelRouter
from tools.filesystem import SafeFileSystem
from tools.git import GitTools
from tools.tests import TestRunner
from tools.run_logger import RunLogger
from agent.repository_agent import RepositoryAgent
from agent.issue_agent import IssueAgent
from agent.coding_agent import CodingAgent
from agent.debugging_agent import DebuggingAgent
from agent.reviewer_agent import ReviewerAgent
from repository.context import RepositoryContext
from ui.sprite_renderer import sprite
from tools.repo_guard import format_guard_report


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


class Orchestrator:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.gh_client = GitHubClient()
        self.repo_mgr = RepositoryManager(self.gh_client)
        self.issue_mgr = IssueManager(self.gh_client)
        self.fork_mgr = ForkManager(self.gh_client)
        self.pr_mgr = PullRequestManager(self.gh_client)
        self.router = ModelRouter(settings.get_task_chains())
        self.repo_agent = RepositoryAgent()
        self.issue_agent = IssueAgent(self.router)
        self.reviewer_agent = ReviewerAgent(self.router)

    def run(self, search_query: str = None, target_repo: str = None, target_issue: int = None):
        try:
            self._run(search_query, target_repo, target_issue)
        except KeyboardInterrupt:
            print("\nInterrupted by user. Exiting cleanly.")
        except Exception as e:
            print("\n" + "=" * 60)
            print("RUN FAILED")
            print("=" * 60)
            print(f"{type(e).__name__}: {e}")
            print("The workspace may be left in a partial state — check "
                  f"{settings.WORKSPACE_DIR} before your next run.")

    def _run(self, search_query: str, target_repo: str, target_issue: int = None):
        run_logger = RunLogger(settings.LOGS_DIR, dry_run=self.dry_run)

        repo = self._select_repository(search_query, target_repo)
        if repo is None:
            run_logger.set_outcome("failed")
            run_logger.note("no repositories found")
            run_logger.finalize()
            return
        print(f"Selected repository: {repo.full_name} ({repo.stargazers_count} stars)")

        if target_issue:
            print(f"\n=== Fetching issue #{target_issue} directly ===")
            raw_issue = self.gh_client.request("GET", f"/repos/{repo.full_name}/issues/{target_issue}")
            if "pull_request" in raw_issue:
                print(f"#{target_issue} is a pull request, not an issue. Stopping.")
                run_logger.set_outcome("failed")
                run_logger.note(f"#{target_issue} is a PR, not an issue")
                run_logger.finalize()
                return
            from models.schemas import IssueInfo
            issue = IssueInfo(
                number=raw_issue["number"],
                title=raw_issue["title"],
                body=raw_issue.get("body", "") or "",
                html_url=raw_issue["html_url"],
                repository_full_name=repo.full_name,
                labels=[l["name"] for l in raw_issue.get("labels", [])],
            )
        else:
            sprite.set_state("thinking")
            sprite.newline()
            print("\n=== Searching issues ===")
            issues_raw = self.issue_mgr.search_issues(repo.full_name, limit=5)
            if not issues_raw:
                print("No open issues found for this repository. Try a different query.")
                run_logger.set_outcome("failed")
                run_logger.note(f"no open issues found for {repo.full_name}")
                run_logger.finalize()
                return

            issue = self.issue_agent.rank_and_select(issues_raw)

        run_logger.set_repo_issue(repo.full_name, issue.number, issue.title)

        print(f"""
============================================================
ISSUE SELECTED
============================================================
Repository: {repo.full_name}
Issue: #{issue.number} - {issue.title}
URL: {issue.html_url}
Labels: {issue.labels}
============================================================
""")
        if not _confirm("Proceed with this issue?"):
            print("Aborted by user.")
            sprite.set_state("idle")
            run_logger.set_outcome("aborted")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        sprite.set_state("working")
        sprite.newline()
        print("\n=== Forking repository ===")
        fork_data = self.fork_mgr.create_fork(repo.full_name)
        fork_owner = fork_data["owner"]["login"]
        print(f"Forked to: {fork_data['full_name']}")
        print("Waiting for fork to become ready...")
        time.sleep(5)

        fork_repo = RepositoryInfo(
            owner=fork_owner,
            name=repo.name,
            full_name=fork_data["full_name"],
            clone_url=fork_data["clone_url"],
            ssh_url=fork_data["ssh_url"],
            default_branch=repo.default_branch,
        )

        print("\n=== Cloning your fork (fresh) ===")
        repo_dir = self.repo_agent.clone(fork_repo, settings.WORKSPACE_DIR)
        fs = SafeFileSystem(repo_dir)
        git_tools = GitTools(repo_dir)
        test_runner = TestRunner(repo_dir)
        coding_agent = CodingAgent(self.router, fs)
        debug_agent = DebuggingAgent(self.router, fs)

        print("\n=== Checking host environment / repo dependencies ===")
        guard_result = test_runner.preflight_check()
        if not guard_result.ok:
            sprite.set_state("sad")
            sprite.newline()
            print(format_guard_report(guard_result))
            run_logger.set_outcome("failed_missing_repo_dependency")
            run_logger.note("host environment or repo dependencies missing — see guard report")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        context = RepositoryContext(repo_dir).assemble_context()

        sprite.set_state("thinking")
        sprite.newline()
        print("\n=== Generating implementation plan ===")
        plan = coding_agent.generate_plan(issue, context)
        print(f"""
============================================================
PROPOSED PLAN
============================================================
Summary: {plan.summary}
Files to modify: {plan.files_to_modify}
Steps:
{chr(10).join('- ' + s for s in plan.steps)}
============================================================
""")
        if not plan.files_to_modify:
            print("Plan produced no files to modify — nothing to do. Stopping.")
            sprite.set_state("sad")
            run_logger.set_outcome("failed")
            run_logger.note("planning produced empty file list")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        if not _confirm("Proceed with implementation?"):
            print("Aborted by user.")
            sprite.set_state("idle")
            run_logger.set_outcome("aborted")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        branch_name = self._create_working_branch(git_tools, issue.number)

        sprite.set_state("working")
        sprite.newline()
        coding_agent.apply_plan(issue, plan)

        sprite.set_state("thinking")
        sprite.newline()
        print("\n=== Running tests ===")
        code, output = test_runner.run_suite()

        if code == -2:
            # Host/dependency problem, not a code problem — never spend an
            # LLM call trying to "fix" a missing system binary.
            sprite.set_state("sad")
            sprite.newline()
            print(output)
            run_logger.set_outcome("failed_missing_repo_dependency")
            run_logger.note("host environment or repo dependencies missing during test run")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        retries = 0
        while code != 0 and retries < settings.MAX_DEBUG_RETRIES:
            sprite.set_state("troubled")
            sprite.newline()
            print(f"Tests failed (attempt {retries + 1}/{settings.MAX_DEBUG_RETRIES}). Output:\n{output[:2000]}")
            for file_path in plan.files_to_modify:
                debug_agent.attempt_fix(file_path, output)
            code, output = test_runner.run_suite()

            if code == -2:
                sprite.set_state("sad")
                sprite.newline()
                print(output)
                run_logger.set_outcome("failed_missing_repo_dependency")
                run_logger.note("host environment or repo dependencies missing during debug retry")
                run_logger.attach_model_calls(self.router.call_log)
                run_logger.finalize()
                return

            retries += 1

        if code != 0:
            print("Tests still failing after max retries. Stopping before push.")
            print(output[:3000])
            sprite.set_state("sad")
            run_logger.set_test_result(passed=False, retries_used=retries)
            run_logger.set_outcome("failed")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        print("\n=== Running lint ===")
        _, lint_output = test_runner.run_lint()
        print(lint_output[:1500])

        diff = git_tools.get_diff()
        if not diff.strip():
            print("Git diff is empty — no actual changes were made. Stopping.")
            sprite.set_state("sad")
            run_logger.set_test_result(passed=True, retries_used=retries)
            run_logger.set_outcome("failed")
            run_logger.note("empty diff")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        sprite.set_state("thinking")
        sprite.newline()
        print("\n=== Requesting code review ===")
        review = self.reviewer_agent.review(issue, diff)

        print(f"""
============================================================
FINAL DIFF
============================================================
{diff[:4000]}

Tests: PASSED
Review approved: {review.approved}
Review feedback: {review.feedback}
============================================================
""")
        if not review.approved:
            print("Reviewer did not approve. Stopping before push.")
            sprite.set_state("sad")
            run_logger.set_test_result(passed=True, retries_used=retries)
            run_logger.set_review_result(approved=False)
            run_logger.set_outcome("failed")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        if self.dry_run:
            print("\n[DRY RUN] Stopping here — no push or PR will be created.")
            run_logger.set_test_result(passed=True, retries_used=retries)
            run_logger.set_review_result(approved=True)
            run_logger.set_outcome("dry_run_complete")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        if not _confirm("Create commit and push?"):
            print("Aborted by user.")
            sprite.set_state("idle")
            run_logger.set_test_result(passed=True, retries_used=retries)
            run_logger.set_review_result(approved=True)
            run_logger.set_outcome("aborted")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        git_tools.commit_all(f"Fix #{issue.number}: {issue.title}")
        git_tools.push("origin", branch_name)

        pr_title = f"Fix #{issue.number}: {issue.title}"
        pr_body = f"Closes #{issue.number}\n\n{plan.summary}\n\nReview notes:\n{review.feedback}"
        print(f"""
============================================================
PULL REQUEST
============================================================
Title: {pr_title}
Description:
{pr_body}
============================================================
""")
        if not _confirm("Create PR?"):
            print("Aborted by user. Branch pushed but no PR created.")
            run_logger.set_test_result(passed=True, retries_used=retries)
            run_logger.set_review_result(approved=True)
            run_logger.set_outcome("pushed_no_pr")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()
            return

        pr = self.pr_mgr.create_pull_request(
            repo.full_name, pr_title, head=f"{fork_owner}:{branch_name}", base=repo.default_branch, body=pr_body
        )
        sprite.set_state("happy")
        sprite.newline()
        print(f"Pull request created: {pr.get('html_url')}")
        run_logger.set_test_result(passed=True, retries_used=retries)
        run_logger.set_review_result(approved=True)
        run_logger.set_outcome("pr_created")
        run_logger.attach_model_calls(self.router.call_log)
        run_logger.finalize()

    def _select_repository(self, search_query: str, target_repo: str) -> RepositoryInfo:
        """
        Supports either a direct --repo target, or a search query.
        When searching, picks randomly from the top N results instead of
        always #1 by stars — avoids repeatedly landing on the same giant
        repo that may have zero open issues.
        """
        if target_repo:
            owner, name = target_repo.split("/", 1)
            raw = self.gh_client.request("GET", f"/repos/{target_repo}")
            return RepositoryInfo(
                owner=owner,
                name=name,
                full_name=raw["full_name"],
                clone_url=raw["clone_url"],
                ssh_url=raw["ssh_url"],
                default_branch=raw.get("default_branch", "main"),
                description=raw.get("description") or "",
                stargazers_count=raw.get("stargazers_count", 0),
                language=raw.get("language") or "",
            )

        sprite.set_state("thinking")
        sprite.newline()
        print("\n=== Searching repositories ===")
        repos_raw = self.repo_mgr.search_repositories(
            search_query, limit=settings.REPO_SELECTION_POOL_SIZE
        )
        if not repos_raw:
            print("No repositories found.")
            return None

        repo_raw = random.choice(repos_raw)
        return RepositoryInfo(
            owner=repo_raw["owner"]["login"],
            name=repo_raw["name"],
            full_name=repo_raw["full_name"],
            clone_url=repo_raw["clone_url"],
            ssh_url=repo_raw["ssh_url"],
            default_branch=repo_raw.get("default_branch", "main"),
            description=repo_raw.get("description") or "",
            stargazers_count=repo_raw.get("stargazers_count", 0),
            language=repo_raw.get("language") or "",
        )

    def _create_working_branch(self, git_tools: GitTools, issue_number: int) -> str:
        """
        Idempotent branch creation: if oss-agent/issue-N already exists
        (e.g. from a crashed previous run), append a short suffix instead
        of failing on 'branch already exists'.
        """
        base_name = f"oss-agent/issue-{issue_number}"
        code, _, _ = git_tools.checkout_branch(base_name)
        if code == 0:
            return base_name

        suffixed_name = f"{base_name}-{int(time.time())}"
        print(f"Branch '{base_name}' already existed — using '{suffixed_name}' instead.")
        git_tools.checkout_branch(suffixed_name)
        return suffixed_name
