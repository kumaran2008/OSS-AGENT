import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings
from models.schemas import RepositoryInfo
from tools.dashboard import dashboard
from tools.diff_explainer import DiffHunkExplainer
from tools.environment_setup import EnvironmentBootstrapper
from tools.git import GitTools
from tools.github import ForkManager, IssueSelector, PullRequestManager
from llm.router import LLMRouter
from tools.run_logger import RunLogger
from tools.filesystem import SafeFileSystem
from ui.sprite_renderer import sprite
from tools.system_tier import CURRENT_TIER, HardwareTier
from tools.tests import TestRunner, format_guard_report

# New Deliberation, Memory & Gating Modules
from tools.agent_bus import blackboard
from tools.agent_memory import EpisodicExecutionMemory, UserProfileMemory
from agent.security_agent import SecurityAgent
from agent.reviewer_agent import ReviewerAgent

from agent.coding_agent import CodingAgent
from agent.debugging_agent import DebuggingAgent
from agent.issue_scorer import IssueTractabilityScorer
from agent.repository_agent import RepositoryAgent
from agent.researcher import RepositoryResearchAgent
from agent.training import distillation_daemon
from tools.sync_training import interactive_sync_prompt



def _confirm(prompt: str) -> bool:
    """Prompt user for confirmation in CLI."""
    try:
        reply = input(f"\n[Approval Gate] {prompt} [y/N]: ").strip().lower()
        return reply in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        return False


def _cleanup_ephemeral_workspace(repo_dir: Path) -> None:
    """Clean up workspace after run completes."""
    if repo_dir and repo_dir.exists():
        try:
            shutil.rmtree(repo_dir)
        except Exception:
            pass


class Orchestrator:
    """
    Central Coordinator managing the autonomous engineering loop:
    Tractability Ranking -> Fork/Clone -> JIT Tooling -> Episodic Recall ->
    Plan -> Code -> Debug -> Adversarial Audit (Security & Reviewer) -> Diff Summary -> PR.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.router = LLMRouter(settings.get_task_chains())
        self.repo_agent = RepositoryAgent(router=self.router)
        self.fork_mgr = ForkManager()
        self.pr_mgr = PullRequestManager()
        self.issue_selector = IssueSelector()
        self.diff_explainer = DiffHunkExplainer()
        self.bootstrapper = EnvironmentBootstrapper()

        # Integrated Memory & Adversarial Gates
        self.user_mem = UserProfileMemory()
        self.ep_mem = EpisodicExecutionMemory()
        self.security_agent = SecurityAgent(self.router)
        self.reviewer_agent = ReviewerAgent(self.router)
        self.distillation_daemon = distillation_daemon

    def _auto_install_dependencies(self, repo_dir: Path, test_runner: TestRunner) -> None:
        """Installs toolchains and dependencies Just-In-Time based on manifest presence."""
        has = lambda fname: (repo_dir / fname).exists()

        # 1. Trigger JIT Environment Toolchain Setup
        self.bootstrapper.bootstrap_for_repo(repo_dir)

        # 2. Package Manager resolution & install
        if has("package.json") and not has("node_modules"):
            from tools.tests import resolve_package_manager_command
            install_cmd = resolve_package_manager_command(repo_dir)
            if install_cmd:
                test_runner.shell.execute(install_cmd, auto_approve_override=True)
        elif has("Cargo.toml") and not (repo_dir / "target").exists():
            test_runner.shell.execute("cargo fetch", auto_approve_override=True)
        elif has("go.mod"):
            test_runner.shell.execute("go mod download", auto_approve_override=True)
        elif has("requirements.txt"):
            pip_cmd = (
                "pip install -r requirements.txt --break-system-packages"
                if "TERMUX_VERSION" in os.environ or "com.termux" in os.environ.get("PREFIX", "")
                else "pip install -r requirements.txt"
            )
            test_runner.shell.execute(pip_cmd, auto_approve_override=True)

    def run(
        self,
        search_query: Optional[str] = None,
        target_repo: Optional[str] = None,
        target_issue: Optional[int] = None,
    ) -> None:
        run_logger = RunLogger()
        repo_dir = None

        try:
            # Reset blackboard for fresh run
            blackboard.clear()
            dashboard.emit("STATE_CHANGE", {"state": "SCANNING_AST"})

            # 1. Resolve Target Repo
            if target_repo:
                repo_info = self.issue_selector.get_repo_info(target_repo)
            else:
                repo_info = self.issue_selector.find_best_repo(search_query)

            if not repo_info:
                print("[Orchestrator] No matching repository found.")
                dashboard.emit("STATE_CHANGE", {"state": "ERROR"})
                return

            # 2. Resolve or Score Target Issue
            if target_issue:
                issue = self.issue_selector.get_issue(repo_info.full_name, target_issue)
            else:
                candidate_issues = self.issue_selector.list_open_issues(repo_info.full_name)
                # Deterministic Tractability Pre-Flight Ranking
                issue = self.repo_agent.rank_and_select_issue(candidate_issues)

            if not issue:
                print("[Orchestrator] No solvable issue found for this repository.")
                dashboard.emit("STATE_CHANGE", {"state": "ERROR"})
                return

            blackboard.publish("Orchestrator", "TARGET_ISSUE", {
                "repo": repo_info.full_name,
                "number": issue.get("number"),
                "title": issue.get("title")
            })

            # 3. Fork and Clone
            sprite.set_state("working")
            sprite.newline()
            print("\n=== Forking repository ===")
            dashboard.emit("STATE_CHANGE", {"state": "WORKING"})
            dashboard.emit("LOG_STREAM", {"message": f"Forking and cloning {repo_info.full_name}..."})

            fork_data = self.fork_mgr.create_fork(repo_info.full_name)
            fork_owner = fork_data["owner"]["login"]
            print(f"Forked to: {fork_data['full_name']}")
            print("Waiting for fork to become ready...")
            time.sleep(5)

            fork_repo = RepositoryInfo(
                owner=fork_owner,
                name=repo_info.name,
                full_name=fork_data["full_name"],
                clone_url=fork_data["clone_url"],
                ssh_url=fork_data["ssh_url"],
                default_branch=repo_info.default_branch,
            )

            print("\n=== Cloning your fork (fresh) ===")
            repo_dir = self.repo_agent.clone(fork_repo, settings.WORKSPACE_DIR)
            fs = SafeFileSystem(repo_dir)
            git_tools = GitTools(repo_dir)
            test_runner = TestRunner(repo_dir)
            coding_agent = CodingAgent(self.router, fs)
            debug_agent = DebuggingAgent(self.router, fs)

            # 4. JIT Preflight Dependencies
            self._auto_install_dependencies(repo_dir, test_runner)

            print("\n=== Checking host environment / repo dependencies ===")
            guard_result = test_runner.preflight_check()
            if not guard_result.ok:
                sprite.set_state("sad")
                sprite.newline()
                dashboard.emit("STATE_CHANGE", {"state": "ERROR"})
                dashboard.emit("LOG_STREAM", {"message": "Missing repo dependencies."})
                print(format_guard_report(guard_result))
                run_logger.set_outcome("failed_missing_repo_dependency")
                run_logger.note("host environment or repo dependencies missing")
                run_logger.attach_model_calls(self.router.call_log)
                run_logger.finalize()
                return

            # 5. Episodic Fix Retrieval & Repository Research
            issue_title = issue.get("title", "")
            issue_body = issue.get("body", "")
            past_fixes = self.ep_mem.recall_similar_fix(f"{issue_title} {issue_body}")
            if past_fixes:
                print(f"\n[Episodic Memory] Found {len(past_fixes)} relevant past resolution(s) in local SQLite.")
                blackboard.publish("EpisodicMemory", "PAST_SOLUTIONS", past_fixes)

            dashboard.emit("STATE_CHANGE", {"state": "SCANNING_AST"})
            dashboard.emit("LOG_STREAM", {"message": "Running Repository Research Agent..."})
            researcher = RepositoryResearchAgent(repo_dir=str(repo_dir))
            approved_research = researcher.present_proposals()
            blackboard.publish("ResearcherAgent", "RESEARCH_PROPOSAL", approved_research)

            branch_name = f"fix-issue-{issue.get('number', int(time.time()))}"
            git_tools.create_branch(branch_name)

            dashboard.emit("STATE_CHANGE", {"state": "PLANNING"})
            plan = coding_agent.create_plan(issue, approved_research)
            blackboard.publish("CodingAgent", "PLAN", plan)

            # 6. Coding & Reflection Loop
            dashboard.emit("STATE_CHANGE", {"state": "CODING"})
            coding_agent.execute_plan(plan)

            retries = 0
            max_retries = 3
            test_passed = False

            while retries < max_retries:
                test_result = test_runner.run_tests()
                if test_result.passed:
                    test_passed = True
                    break
                retries += 1
                dashboard.emit("STATE_CHANGE", {"state": "REFLECTING"})
                debug_agent.diagnose_and_patch(issue, test_result.output)

            # 7. Structural Diff Audit & Adversarial Pre-Review Gates
            raw_diff = git_tools.diff()
            diff_audit = self.diff_explainer.format_review_summary(raw_diff)

            print("\n" + "=" * 55)
            print(diff_audit)
            print("=" * 55 + "\n")

            # Adversarial Security Audit
            sec_result = self.security_agent.audit_diff(raw_diff)
            blackboard.publish("SecurityAgent", "SECURITY_AUDIT", sec_result)
            if not sec_result["passed"]:
                print("\n[SECURITY GATE WARNING] Potential security or injection issues flagged:")
                for r in sec_result["reasons"]:
                    print(f"  • {r}")

            # Adversarial Reviewer Audit
            rev_result = self.reviewer_agent.review_patch(raw_diff, test_passed)
            blackboard.publish("ReviewerAgent", "REVIEW_DECISION", rev_result)
            if not rev_result["approved"]:
                print("\n[REVIEWER GATE CRITIQUE] Quality issues flagged:")
                for c in rev_result["critiques"]:
                    print(f"  • {c}")

            # If tests passed and patch verified, log resolution into Episodic Memory
            if test_passed and raw_diff:
                self.ep_mem.record_resolution(
                    repo_name=repo_info.full_name,
                    error_signature=f"{issue_title}\n{issue_body[:300]}",
                    resolution_patch=raw_diff[:2000],
                    explanation=plan.get("summary", "Resolved via automated repair loop.")
                )

            dashboard.emit("LOG_STREAM", {"message": diff_audit})
            dashboard.emit("STATE_CHANGE", {"state": "AWAITING_APPROVAL"})

            if self.dry_run:
                print("\n[Dry Run] Completed verification successfully. Skipping commit & push.")
                dashboard.emit("STATE_CHANGE", {"state": "SUCCESS"})
                return

            if not _confirm("Create commit and push?"):
                dashboard.emit("LOG_STREAM", {"message": "User aborted commit and push."})
                run_logger.set_test_result(passed=test_passed, retries_used=retries)
                run_logger.set_review_result(approved=False)
                run_logger.set_outcome("aborted")
                run_logger.attach_model_calls(self.router.call_log)
                run_logger.finalize()
                return

            issue_num = issue.get("number")
            issue_title = issue.get("title")
            git_tools.commit_all(f"Fix #{issue_num}: {issue_title}")
            git_tools.push("origin", branch_name)

            pr_title = f"Fix #{issue_num}: {issue_title}"
            pr_body = (
                f"Closes #{issue_num}\n\n"
                f"### Summary of Changes\n{plan.get('summary', '')}\n\n"
                f"{diff_audit}"
            )

            if not _confirm("Create PR?"):
                dashboard.emit("STATE_CHANGE", {"state": "SUCCESS"})
                dashboard.emit("LOG_STREAM", {"message": "Branch pushed successfully (no PR created)."})
                run_logger.set_test_result(passed=test_passed, retries_used=retries)
                run_logger.set_review_result(approved=True)
                run_logger.set_outcome("pushed_no_pr")
                run_logger.attach_model_calls(self.router.call_log)
                run_logger.finalize()
                return

            pr = self.pr_mgr.create_pull_request(
                repo_info.full_name,
                pr_title,
                head=f"{fork_owner}:{branch_name}",
                base=repo_info.default_branch,
                body=pr_body,
            )
            dashboard.emit("STATE_CHANGE", {"state": "SUCCESS"})
            dashboard.emit("LOG_STREAM", {"message": f"Pull Request created: {pr.get('html_url')}"})
            run_logger.set_test_result(passed=test_passed, retries_used=retries)
            run_logger.set_review_result(approved=True)
            run_logger.set_outcome("pr_created")
            run_logger.attach_model_calls(self.router.call_log)
            run_logger.finalize()

        finally:
            if repo_dir:
                _cleanup_ephemeral_workspace(Path(repo_dir))
            try:
                self.distillation_daemon.execute_distillation_cycle()
                import sys
                if sys.stdin.isatty():
                    interactive_sync_prompt()
            except Exception as e:
                print(f"[Orchestrator] Distillation / sync lifecycle notice: {e}")
