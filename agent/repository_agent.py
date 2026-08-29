import shutil
import subprocess
from pathlib import Path
from models.schemas import RepositoryInfo


class RepositoryAgent:
    """
    Handles cloning. Always starts from a clean slate — a previous run's
    leftover folder was causing stale-diff bugs where the agent edited an
    old checkout instead of the freshly forked repo.
    """

    def clone(self, repo: RepositoryInfo, destination: Path) -> Path:
        target_dir = destination / repo.name
        if target_dir.exists():
            shutil.rmtree(target_dir)

        subprocess.run(
            ["git", "clone", repo.clone_url, str(target_dir)],
            check=True,
        )
        return target_dir
