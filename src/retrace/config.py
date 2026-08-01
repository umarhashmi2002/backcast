"""Runtime configuration, loaded from environment variables (and ``.env`` locally).

All settings are prefixed ``RETRACE_`` except ``AWS_REGION``, which follows the
standard AWS convention so the same value drives boto3.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_prefix="RETRACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- CockroachDB -------------------------------------------------------
    database_url: str = "postgresql://root@localhost:26257/retrace?sslmode=disable"

    # --- AWS / Bedrock -----------------------------------------------------
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("AWS_REGION", "RETRACE_AWS_REGION"),
    )
    bedrock_model_id: str = "us.anthropic.claude-sonnet-5"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dims: int = 1024
    artifact_bucket: str = ""

    # --- Memory tuning -----------------------------------------------------
    consolidation_lookback_hours: int = 24
    memory_decay_halflife_days: float = 30.0
    recall_top_k: int = 8

    # --- Observability -----------------------------------------------------
    log_level: str = "INFO"
    env: str = "local"

    @property
    def is_local(self) -> bool:
        return self.env.lower() in {"local", "dev", "test"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached ``Settings`` instance."""
    return Settings()
