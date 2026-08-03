"""Relevance scoring for memory recall.

Vector indexes rank by raw distance; memory recall additionally weighs recency
and (for long-term memory) a decaying retrieval score, so that *what mattered*
is preferred over merely *what is nearest*.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Exact cosine similarity between two vectors (0.0 if either is degenerate)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def cosine_from_l2(distance: float) -> float:
    """Convert an L2 distance between unit vectors to cosine similarity.

    For L2-normalized vectors, ||a - b||^2 = 2 - 2·cos(a, b), so
    cos = 1 - d^2 / 2. Clamped to [-1, 1].
    """
    cos = 1.0 - (distance * distance) / 2.0
    return max(-1.0, min(1.0, cos))


def recency_weight(age_days: float, halflife_days: float) -> float:
    """Exponential recency in (0, 1]; 1.0 at age 0, 0.5 at one half-life."""
    if halflife_days <= 0:
        return 1.0
    return float(0.5 ** (max(0.0, age_days) / halflife_days))


def _age_days(moment: datetime | None) -> float:
    if moment is None:
        return 0.0
    now = datetime.now(UTC)
    ref = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return max(0.0, (now - ref).total_seconds() / 86_400.0)


def evidence_score(distance: float, observed_at: datetime | None, halflife_days: float) -> float:
    """Blend semantic similarity with mild recency preference."""
    similarity = cosine_from_l2(distance)
    recency = recency_weight(_age_days(observed_at), halflife_days)
    return similarity * (0.7 + 0.3 * recency)


def memory_score(
    distance: float,
    retrieval_score: float,
    importance: float,
    last_accessed_at: datetime | None,
    halflife_days: float,
) -> float:
    """Score long-term (semantic/procedural) memory for recall ranking."""
    similarity = cosine_from_l2(distance)
    recency = recency_weight(_age_days(last_accessed_at), halflife_days)
    strength = 0.5 + 0.5 * max(0.0, min(1.0, importance))
    return similarity * strength * max(0.0, min(1.0, retrieval_score)) * (0.5 + 0.5 * recency)
