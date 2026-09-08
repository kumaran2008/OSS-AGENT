import random
import shutil
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
from agent.researcher import RepositoryResearchAgent
from tools.system_info import select_execution_mode
from repository.context import RepositoryContext
from ui.sprite_renderer import sprite
from tools.repo_guard import format_guard_report


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


def _cleanup_ephemeral_workspace(repo_dir: Path) -> None:
    """Safely cleans up temporary workspace clones to prevent disk clutter and branch collisions."""
    if repo_dir and repo_dir.exists():
        try:
            print(f"\n[Workspace Cleaner] Cleaning up temporary workspace: {repo_dir}")
            shutil.rmtree(repo_dir, ignore_errors=True)
            print("[Workspace Cleaner] Workspace cleaned successfully.")
        except Exception as e:
            print(f"[Workspace Cleaner Warning] Failed to clean workspace: {e}")


class Orchestrator:
    def __init__(self, dry_run: bool = False, execution_mode: str = None):
        self.dry_run = dry_run
        self.gh_client = GitHubClient()
        self.repo_mgr = RepositoryManager(self.gh_client)
        self.issue_mgr = IssueManager(self.gh_client)
        self.fork_mgr = ForkManager(self.gh_client)
        self.pr_mgr = PullRequestManager(self.gh_client)

        # 1. Hardware Sensing & Execution Mode Selection.
        # An explicit execution_mode (e.g. from a --mode CLI flag) skips
        # the interactive prompt entirely — important for scripted/
        # non-interactive use, where select_execution_mode()'s input()
        # call would otherwise block every single run.
        self.execution_mode = execution_mode or select_execution_mode()

        # 2. Token & Hardware-Aware Model Router
        self.router = ModelRouter(settings.get_task_chains(), mode=self.execution_mode)

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
        repo_dir = None

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

        try:
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
            # Auto-install dependencies for whichever language/build system
            # this repo uses — avoids requiring a manual setup step that
            # would be wiped anyway on the next run's fresh clone. Each
            # check only runs its install command if the corresponding
            # lockfile/manifest exists AND the dependency output folder
            # is missing, so this is a no-op on repos with nothing to install.
            self._auto_install_dependencies(repo_dir, test_runner)
         
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

            # Autonomous Repository Research Agent Stage
            researcher = RepositoryResearchAgent(repo_dir=str(repo_dir))
            approved_research = researcher.present_proposals()
            if not approved_research:
                print("[Info] Skipping Research Agent proposals. Proceeding with issue resolution...")

            context = RepositoryContext(repo_dir).assemble_context(issue.title, issue.body)

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

            print("\n=== Capturing pre-patch test baseline ===")
            baseline_code, baseline_output = test_runner.run_suite()
            if baseline_code == -2:
                sprite.set_state("sad")
                sprite.newline()
                print(baseline_output)
                run_logger.set_outcome("failed_missing_repo_dependency")
                run_logger.note("host environment issue detected in baseline, before any patch applied")
                run_logger.attach_model_calls(self.router.call_log)
                run_logger.finalize()
                return
            if baseline_code != 0:
                print("Note: this repo's test suite has pre-existing failures unrelated to our change.")
                print("Only NEW failures introduced by the patch will trigger the debug loop.")

            sprite.set_state("working")
            sprite.newline()
            coding_agent.apply_plan(issue, plan)

            sprite.set_state("thinking")
            sprite.newline()
            print("\n=== Running tests ===")
            code, output = test_runner.run_suite()

            baseline_failures = test_runner.parse_failing_tests(baseline_output)
            post_failures = test_runner.parse_failing_tests(output)
            new_failures = post_failures - baseline_failures

            if code != 0 and len(new_failures) == 0:
                print("\n[Test Baseline Guard] Post-patch failures are identical to pre-patch baseline.")
                print("No new regressions introduced by our patch. Continuing to review.")
                code = 0
            elif len(new_failures) > 0:
                print(f"\n[Test Baseline Guard] Detected {len(new_failures)} NEW regression(s) introduced by patch:")
                for f in new_failures:
                    print(f"  - {f}")

            if code == -2:
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

            review_retries = 0
            max_review_retries = settings.MAX_DEBUG_RETRIES

            while not review.approved and review_retries < max_review_retries:
                print(f"""
============================================================
REVIEW REJECTED (attempt {review_retries + 1}/{max_review_retries})
============================================================
Feedback: {review.feedback}
============================================================
Revising and re-reviewing...
""")
                sprite.set_state("troubled")
                sprite.newline()

                for file_path in plan.files_to_modify:
                    coding_agent.revise_file_patch(issue, plan, file_path, review.feedback)

                print("\n=== Re-running tests after revision ===")
                code, output = test_runner.run_suite()
                if code == -2:
                    sprite.set_state("sad")
                    sprite.newline()
                    print(output)
                    run_logger.set_outcome("failed_missing_repo_dependency")
                    run_logger.note("host environment issue during review-retry revision")
                    run_logger.attach_model_calls(self.router.call_log)
                    run_logger.finalize()
                    return
                if code != 0:
                    print("Revision broke the tests. Stopping before push.")
                    sprite.set_state("sad")
                    run_logger.set_test_result(passed=False, retries_used=retries)
                    run_logger.set_review_result(approved=False)
                    run_logger.set_outcome("failed")
                    run_logger.attach_model_calls(self.router.call_log)
                    run_logger.finalize()
                    return

                diff = git_tools.get_diff()
                print("\n=== Re-requesting code review ===")
                review = self.reviewer_agent.review(issue, diff)
                review_retries += 1

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
                print(f"Reviewer still did not approve after {max_review_retries} revision attempt(s). Stopping before push.")
                sprite.set_state("sad")
                run_logger.set_test_result(passed=True, retries_used=retries)
                run_logger.set_review_result(approved=False)
                run_logger.set_outcome("failed")
                run_logger.note(f"review rejected after {review_retries} revision attempt(s)")
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

        finally:
            # Always clean up the cloned workspace — dry run, successful
            # real run, or a mid-run crash — to prevent disk clutter and
            # stale-branch collisions on the next run against this repo.
            if repo_dir:
                _cleanup_ephemeral_workspace(Path(repo_dir))
    def _auto_install_dependencies(self, repo_dir: Path, test_runner: TestRunner) -> None:
        """
        Detects the repo's language/build system and installs its
        dependencies automatically if they're missing — Node (npm),
        Rust (cargo fetch), Go (go mod download), Python (pip install -r
        requirements.txt), and C/C++ (cmake configure only, since building
        happens as part of the test step for those). Each check is
        independent, so a repo only triggers the install relevant to it.
        """
        has = lambda fname: (repo_dir / fname).exists()

        if has("package.json") and not has("node_modules"):
            from tools.tests import detect_node_package_manager, resolve_package_manager_command
            manager = detect_node_package_manager(repo_dir)
            install_cmd = resolve_package_manager_command(repo_dir)
            if install_cmd:
                print(f"\n=== Installing Node dependencies ({install_cmd}, detected: {manager}) ===")
                code, stdout, stderr = test_runner.shell.execute(install_cmd, auto_approve_override=True)
                print("Node dependencies installed successfully." if code == 0
                      else f"{install_cmd} failed:\n{stdout}\n{stderr}")
            else:
                print(f"\n[Warning] Detected package manager '{manager}' but no way to run it "
                      f"(not installed, and npx/corepack unavailable). Skipping dependency install.")

        elif has("Cargo.toml") and not (repo_dir / "target").exists():
            print("\n=== Fetching Rust dependencies (cargo fetch) ===")
            code, stdout, stderr = test_runner.shell.execute("cargo fetch", auto_approve_override=True)
            print("Rust dependencies fetched successfully." if code == 0
                  else f"cargo fetch failed:\n{stdout}\n{stderr}")

        elif has("go.mod"):
            print("\n=== Downloading Go dependencies (go mod download) ===")
            code, stdout, stderr = test_runner.shell.execute("go mod download", auto_approve_override=True)
            print("Go dependencies downloaded successfully." if code == 0
                  else f"go mod download failed:\n{stdout}\n{stderr}")

        elif has("requirements.txt"):
            print("\n=== Installing Python dependencies (pip install -r requirements.txt) ===")
            pip_cmd = "pip install -r requirements.txt --break-system-packages" \
                if "TERMUX_VERSION" in __import__("os").environ else "pip install -r requirements.txt"
            code, stdout, stderr = test_runner.shell.execute(pip_cmd, auto_approve_override=True)
            print("Python dependencies installed successfully." if code == 0
                  else f"pip install failed:\n{stdout}\n{stderr}")

        # CMake/Meson C/C++ projects intentionally skipped here — their
        # "install" step (cmake configure, meson setup) already happens
        # as part of TestRunner.run_suite() itself, since the build
        # directory is a required input to running tests, not a
        # separate prerequisite.

    
    def _select_repository(self, search_query: str, target_repo: str) -> RepositoryInfo:
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
        base_name = f"oss-agent/issue-{issue_number}"
        code, _, _ = git_tools.checkout_branch(base_name)
        if code == 0:
            return base_name

        suffixed_name = f"{base_name}-{int(time.time())}"
        print(f"Branch '{base_name}' already existed — using '{suffixed_name}' instead.")
        git_tools.checkout_branch(suffixed_name)
        return suffixed_name
