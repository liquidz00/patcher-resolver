"""
Runtime configuration, read from environment variables (and a local ``.env``).

Field names map to upper-case env vars (``patcher_admin_token`` <- ``PATCHER_ADMIN_TOKEN``).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Patcher API
    api_base_url: str = "https://api.patcherctl.dev"
    patcher_admin_token: str

    # GitHub PAT to dodge the api.github.com 60/hr limit Installomator's
    # *FromGit helpers hit during resolution.
    github_token: str

    # Local checkouts on this host (kept current with `git pull` each run).
    installomator_dir: str
    resolve_label_script: str

    temporal_address: str = "localhost:7233"
    temporal_task_queue: str = "patcher-resolver"

    concurrency: int = 8
    label_timeout_minutes: int = 10
    work_dir: str = "~/.patcher-resolver"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
