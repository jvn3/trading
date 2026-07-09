"""Application settings.

Loaded from environment variables and an optional local ``.env`` file. Secrets never live in
code or version control; ``.env.example`` documents the expected keys.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the AlphaDash backend."""

    model_config = SettingsConfigDict(
        env_prefix="ALPHADASH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Deployment
    app_env: str = "development"

    # Hard product invariant: paper-only until real-money mode is explicitly built and gated (§13.4,
    # §16 Phase 5). This flag exists so the value is visible/asserted everywhere; flipping it is NOT
    # sufficient to enable real money.
    trading_mode: str = "paper"

    # Persistence — defaults to the sqlite db already present under backend/.
    database_url: str = "sqlite:///./alphadash.db"

    # CORS origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (one read of the environment per process)."""
    return Settings()
