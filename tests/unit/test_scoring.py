"""Unit tests for recall scoring (no database required)."""

from __future__ import annotations

from retrace.memory.scoring import cosine_from_l2, evidence_score, recency_weight


def test_cosine_from_l2_bounds() -> None:
    assert cosine_from_l2(0.0) == 1.0  # identical unit vectors
    assert cosine_from_l2(2.0) == -1.0  # opposite unit vectors
    assert -1.0 <= cosine_from_l2(1.4) <= 1.0


def test_recency_weight_halflife() -> None:
    assert recency_weight(0.0, 30.0) == 1.0
    assert recency_weight(30.0, 30.0) == 0.5
    assert recency_weight(60.0, 30.0) == 0.25
    assert recency_weight(10.0, 0.0) == 1.0  # guard against zero half-life


def test_evidence_score_prefers_closer() -> None:
    near = evidence_score(0.1, None, 30.0)
    far = evidence_score(1.2, None, 30.0)
    assert near > far
