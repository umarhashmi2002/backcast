"""Shared fixtures for integration tests (require a live CockroachDB)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest

from retrace.config import Settings
from retrace.db import migrate
from retrace.db.connection import connect
from retrace.memory import HashEmbedder, MemoryEngine


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema() -> None:
    """Apply migrations once; skip all integration tests if the DB is unreachable."""
    try:
        migrate.run()
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"CockroachDB not reachable ({exc}); run `make db-up`", allow_module_level=False
        )


@pytest.fixture
def settings() -> Settings:
    # Offline embedder keeps integration tests independent of AWS credentials.
    return Settings(embedding_model_id="hash")


@pytest.fixture
def engine(settings: Settings) -> Iterator[MemoryEngine]:
    eng = MemoryEngine(
        conn=connect(settings.database_url),
        embedder=HashEmbedder(settings.embedding_dims),
        settings=settings,
    )
    yield eng
    eng.close()


@pytest.fixture
def org() -> str:
    """A unique tenant id per test, so reruns never collide on unique keys."""
    return f"test-{uuid4().hex[:8]}"
