"""Semantic memory — distilled, revisable knowledge with retrieval decay.

Facts are never physically deleted: they are superseded (belief revision) or have
their ``retrieval_score`` decayed so they surface less often, preserving the record
that consolidation and audit depend on.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from ..config import Settings, get_settings
from ..db.connection import Connection, vector_literal
from .embeddings import Embedder
from .models import RecalledFact, SemanticFact
from .scoring import memory_score


class SemanticStore:
    def __init__(
        self, conn: Connection, embedder: Embedder, settings: Settings | None = None
    ) -> None:
        self._conn = conn
        self._embedder = embedder
        self._settings = settings or get_settings()

    def add(
        self,
        org_id: str,
        statement: str,
        *,
        source: str = "consolidation",
        service: str | None = None,
        confidence: float = 0.6,
        importance: float = 0.5,
        embedding: Sequence[float] | None = None,
    ) -> SemanticFact:
        vector = vector_literal(
            embedding if embedding is not None else self._embedder.embed_one(statement)
        )
        row = self._conn.execute(
            "INSERT INTO semantic_memory (org_id, statement, source, service, confidence, importance, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::VECTOR) RETURNING id, created_at",
            (org_id, statement, source, service, confidence, importance, vector),
        ).fetchone()
        assert row is not None
        return SemanticFact(
            id=row["id"],
            org_id=org_id,
            statement=statement,
            source=source,
            service=service,
            confidence=confidence,
            importance=importance,
            created_at=row["created_at"],
        )

    def recall(
        self, org_id: str, query: str, *, top_k: int | None = None, service: str | None = None
    ) -> list[RecalledFact]:
        k = top_k or self._settings.recall_top_k
        query_vector = vector_literal(self._embedder.embed_one(query))
        sql = (
            "SELECT id, statement, service, confidence, importance, retrieval_score, last_accessed_at, "
            "embedding <-> %s::VECTOR AS distance FROM semantic_memory "
            "WHERE org_id = %s AND embedding IS NOT NULL AND valid_until IS NULL"
        )
        params: list[object] = [query_vector, org_id]
        if service is not None:
            sql += " AND (service = %s OR service IS NULL)"
            params.append(service)
        sql += " ORDER BY distance LIMIT %s"
        params.append(k * 3)

        rows = self._conn.execute(sql, params).fetchall()
        halflife = self._settings.memory_decay_halflife_days
        facts = [
            RecalledFact(
                id=row["id"],
                statement=row["statement"],
                service=row["service"],
                confidence=float(row["confidence"]),
                retrieval_score=float(row["retrieval_score"]),
                distance=float(row["distance"]),
                score=memory_score(
                    float(row["distance"]),
                    float(row["retrieval_score"]),
                    float(row["importance"]),
                    row["last_accessed_at"],
                    halflife,
                ),
            )
            for row in rows
        ]
        facts.sort(key=lambda f: f.score, reverse=True)
        return facts[:k]

    def find_similar(
        self, org_id: str, embedding: Sequence[float], *, max_distance: float = 0.4
    ) -> RecalledFact | None:
        """Return the nearest existing fact within ``max_distance`` (for dedup)."""
        row = self._conn.execute(
            "SELECT id, statement, service, confidence, retrieval_score, "
            "embedding <-> %s::VECTOR AS distance FROM semantic_memory "
            "WHERE org_id = %s AND embedding IS NOT NULL AND valid_until IS NULL "
            "ORDER BY distance LIMIT 1",
            (vector_literal(embedding), org_id),
        ).fetchone()
        if row is None or float(row["distance"]) > max_distance:
            return None
        return RecalledFact(
            id=row["id"],
            statement=row["statement"],
            service=row["service"],
            confidence=float(row["confidence"]),
            retrieval_score=float(row["retrieval_score"]),
            distance=float(row["distance"]),
            score=0.0,
        )

    def touch(self, fact_id: UUID | str) -> None:
        """Reinforce a fact on access: reset retrieval score, bump access count."""
        self._conn.execute(
            "UPDATE semantic_memory SET access_count = access_count + 1, "
            "last_accessed_at = now(), retrieval_score = 1.0, updated_at = now() WHERE id = %s",
            (fact_id,),
        )

    def supersede(self, old_id: UUID | str, new_id: UUID | str) -> None:
        self._conn.execute(
            "UPDATE semantic_memory SET valid_until = now(), superseded_by = %s, updated_at = now() "
            "WHERE id = %s AND valid_until IS NULL",
            (new_id, old_id),
        )

    def decay(self, org_id: str, *, halflife_days: float | None = None) -> int:
        """Recompute retrieval_score = 0.5 ^ (days_since_access / halflife). Idempotent."""
        halflife = halflife_days or self._settings.memory_decay_halflife_days
        rows = self._conn.execute(
            "UPDATE semantic_memory SET retrieval_score = "
            "pow(0.5::FLOAT8, (EXTRACT(EPOCH FROM (now() - COALESCE(last_accessed_at, created_at))) "
            "/ 86400.0) / %s), updated_at = now() "
            "WHERE org_id = %s AND valid_until IS NULL RETURNING id",
            (halflife, org_id),
        ).fetchall()
        return len(rows)
