import click
from config.settings import validate_settings
from agent.orchestrator import Orchestrator
from config.settings import validate_settings, settings

@click.command()
@click.option("--query", default=None, help="GitHub repo search query, e.g. 'language:python stars:>500'")
@click.option("--repo", default=None, help="Target a specific repo directly, e.g. 'psf/requests' (skips search)")
@click.option("--issue", default=None, type=int, help="Target a specific issue number directly (requires --repo)")
@click.option("--dry-run", is_flag=True, default=False, help="Run the full pipeline but stop before any push/PR")
def run(query, repo, issue, dry_run):
    """OSS Contribution Agent — autonomous GitHub issue fixer with human approval gates."""
    validate_settings()
    settings.validate_task_chains()

    if issue and not repo:
        raise click.UsageError("--issue requires --repo to also be set (e.g. --repo owner/name --issue 123)")

    if not repo and not query:
        query = click.prompt("Repository search query", default="language:python stars:>500")

    Orchestrator(dry_run=dry_run).run(search_query=query, target_repo=repo, target_issue=issue)


if __name__ == "__main__":
    run()
