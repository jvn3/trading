"""Pydantic-based settings loaded from .env.

A single ``Settings`` instance is exposed via :func:`get_settings`. Modules that
need config should call that rather than re-reading ``os.environ``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. See ``.env.example`` for the full list."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Alpaca (paper)
    alpaca_api_key: str = Field(..., alias="ALPACA_API_KEY")
    alpaca_secret_key: str = Field(..., alias="ALPACA_SECRET_KEY")
    alpaca_base_url: str = Field(
        "https://paper-api.alpaca.markets", alias="ALPACA_BASE_URL"
    )
    alpaca_account_id: str | None = Field(None, alias="ALPACA_ACCOUNT_ID")

    # FMP
    fmp_api_key: str = Field(..., alias="FMP_API_KEY")

    # Paths
    obsidian_vault_path: Path = Field(..., alias="OBSIDIAN_VAULT_PATH")
    data_dir: Path = Field(Path("./data"), alias="DATA_DIR")
    db_url: str = Field("sqlite:///./data/jay_trading.db", alias="DB_URL")

    # Mode
    app_env: str = Field("development", alias="APP_ENV")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("alpaca_base_url")
    @classmethod
    def _enforce_paper(cls, v: str) -> str:
        # Hard rule #1 from the implementation plan: paper only, ever.
        if "paper-" not in v:
            raise ValueError(
                f"ALPACA_BASE_URL must point at paper trading "
                f"(contain 'paper-'). Got: {v!r}"
            )
        return v

    @property
    def vault_trading_root(self) -> Path:
        """The root directory inside the vault where we write notes."""
        return self.obsidian_vault_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, validated Settings instance."""
    return Settings()  # type: ignore[call-arg]
