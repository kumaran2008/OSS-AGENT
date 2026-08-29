import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    OPENROUTER_CODING_MODEL: str = os.getenv("OPENROUTER_CODING_MODEL", "anthropic/claude-3.5-sonnet")
    OPENROUTER_REVIEW_MODEL: str = os.getenv("OPENROUTER_REVIEW_MODEL", "anthropic/claude-3.5-sonnet")
    OPENROUTER_ANALYSIS_MODEL: str = os.getenv("OPENROUTER_ANALYSIS_MODEL", "openai/gpt-4o-mini")
     
    AUTO_APPROVE_COMMANDS: bool = os.getenv("AUTO_APPROVE_COMMANDS", "false").lower() == "true"
    MAX_DEBUG_RETRIES: int = int(os.getenv("MAX_DEBUG_RETRIES", "3"))

    # How many top search results to consider before picking one (adds diversity)
    REPO_SELECTION_POOL_SIZE: int = int(os.getenv("REPO_SELECTION_POOL_SIZE", "5"))
    # New: comma-separated fallback chains per task. Falls back to the
    # single-model env vars above if a chain isn't explicitly set, so
    # existing .env files keep working without changes.
    MODELS_PLANNING: str = os.getenv("MODELS_PLANNING", "")
    MODELS_CODING: str = os.getenv("MODELS_CODING", "")
    MODELS_REVIEW: str = os.getenv("MODELS_REVIEW", "")
    MODELS_DEBUG: str = os.getenv("MODELS_DEBUG", "")
    MODELS_ANALYSIS: str = os.getenv("MODELS_ANALYSIS", "")

    def get_task_chains(self) -> dict:
        def chain_or_fallback(env_value: str, fallback_model: str) -> list:
            if env_value.strip():
                return [m.strip() for m in env_value.split(",") if m.strip()]
            return [fallback_model]

        return {
            "planning": chain_or_fallback(self.MODELS_PLANNING, self.OPENROUTER_CODING_MODEL),
            "coding": chain_or_fallback(self.MODELS_CODING, self.OPENROUTER_CODING_MODEL),
            "review": chain_or_fallback(self.MODELS_REVIEW, self.OPENROUTER_REVIEW_MODEL),
            "debug": chain_or_fallback(self.MODELS_DEBUG, self.OPENROUTER_CODING_MODEL),
            "analysis": chain_or_fallback(self.MODELS_ANALYSIS, self.OPENROUTER_ANALYSIS_MODEL),
        }
    BASE_DIR: Path = Path(__file__).parent.parent.resolve()
    WORKSPACE_DIR: Path = BASE_DIR / os.getenv("WORKSPACE_DIR", "workspace")
    LOGS_DIR: Path = BASE_DIR / os.getenv("LOGS_DIR", "logs")

settings = Settings()
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)

def validate_settings() -> None:
    """Fail fast with a clear message instead of crashing mid-pipeline later."""
    missing = []
    if not settings.OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")
    if not settings.GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")

    if missing:
        print("=" * 60)
        print("CONFIGURATION ERROR — missing required .env values:")
        for key in missing:
            print(f"  - {key}")
        print("Add them to your .env file and try again.")
        print("=" * 60)
        sys.exit(1)
