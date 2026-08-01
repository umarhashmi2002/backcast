"""Unit tests for the offline HashEmbedder (no database/AWS required)."""

from __future__ import annotations

import math

from retrace.memory.embeddings import HashEmbedder


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_dimensions_and_normalized() -> None:
    emb = HashEmbedder(256)
    vec = emb.embed_one("database connection pool saturated")
    assert len(vec) == 256
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-9)


def test_deterministic() -> None:
    emb = HashEmbedder(128)
    assert emb.embed_one("connection leak") == emb.embed_one("connection leak")


def test_shared_tokens_are_more_similar() -> None:
    emb = HashEmbedder(512)
    query = emb.embed_one("database connection pool exhausted")
    similar = emb.embed_one("database connection pool saturated at maximum")
    unrelated = emb.embed_one("nightly cron job finished successfully")
    assert _dot(query, similar) > _dot(query, unrelated)
