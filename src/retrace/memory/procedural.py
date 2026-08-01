"""Procedural memory — remediations that worked, weighted by observed outcomes.

Matched to new incidents by the similarity of their *trigger pattern* (the symptom),
and ranked by a Laplace-smoothed success rate so procedures that keep working rise.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from ..config import Settings, get_settings
from ..db.connection import Connection, vector_literal
from .embeddings import Embedder
from .models import Procedure, RecalledProcedure
from .scoring import memory_score


def _laplace_confidence(success: int, failure: int) -> float:
    return (success + 1.0) / (success + failure + 2.0)


class ProceduralStore:
    def __init__(
        self, conn: Connection, embedder: Embedder, settings: Settings | None = None
    ) -> None:
        self._conn = conn
        self._embedder = embedder
        self._settings = settings or get_settings()

    def add(
        self,
        org_id: str,
        name: str,
        trigger_pattern: str,
        steps: str,
        *,
        service: str | None = None,
        source_incident_id: UUID | str | None = None,
        embedding: Sequence[float] | None = None,
    ) -> Procedure:
        vector = vector_literal(
            embedding if embedding is not None else self._embedder.embed_one(trigger_pattern)
        )
        row = self._conn.execute(
            "INSERT INTO procedural_memory (org_id, name, trigger_pattern, steps, service, embedding, source_incident_id) "
            "VALUES (%s, %s, %s, %s, %s, %s::VECTOR, %s) RETURNING id",
            (org_id, name, trigger_pattern, steps, service, vector, source_incident_id),
        ).fetchone()
        assert row is not None
        return Procedure(
            id=row["id"],
            org_id=org_id,
            name=name,
            trigger_pattern=trigger_pattern,
            steps=steps,
            service=service,
            source_incident_id=UUID(str(source_incident_id)) if source_incident_id else None,
        )

    def recall(
        self, org_id: str, query: str, *, top_k: int | None = None
    ) -> list[RecalledProcedure]:
        k = top_k or self._settings.recall_top_k
        query_vector = vector_literal(self._embedder.embed_one(query))
        rows = self._conn.execute(
            "SELECT id, name, trigger_pattern, steps, success_count, failure_count, "
            "retrieval_score, last_used_at, embedding <-> %s::VECTOR AS distance "
            "FROM procedural_memory WHERE org_id = %s AND embedding IS NOT NULL "
            "ORDER BY distance LIMIT %s",
            (query_vector, org_id, k * 3),
        ).fetchall()
        halflife = self._settings.memory_decay_halflife_days
        procedures = [
            RecalledProcedure(
                id=row["id"],
                name=row["name"],
                trigger_pattern=row["trigger_pattern"],
                steps=row["steps"],
                success_count=int(row["success_count"]),
                failure_count=int(row["failure_count"]),
                distance=float(row["distance"]),
                score=memory_score(
                    float(row["distance"]),
                    float(row["retrieval_score"]),
                    _laplace_confidence(int(row["success_count"]), int(row["failure_count"])),
                    row["last_used_at"],
                    halflife,
                ),
            )
            for row in rows
        ]
        procedures.sort(key=lambda p: p.score, reverse=True)
        return procedures[:k]

    def find_similar(
        self, org_id: str, embedding: Sequence[float], *, max_distance: float = 0.4
    ) -> RecalledProcedure | None:
        row = self._conn.execute(
            "SELECT id, name, trigger_pattern, steps, success_count, failure_count, "
            "embedding <-> %s::VECTOR AS distance FROM procedural_memory "
            "WHERE org_id = %s AND embedding IS NOT NULL ORDER BY distance LIMIT 1",
            (vector_literal(embedding), org_id),
        ).fetchone()
        if row is None or float(row["distance"]) > max_distance:
            return None
        return RecalledProcedure(
            id=row["id"],
            name=row["name"],
            trigger_pattern=row["trigger_pattern"],
            steps=row["steps"],
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            distance=float(row["distance"]),
            score=0.0,
        )

    def record_outcome(self, procedure_id: UUID | str, *, success: bool) -> None:
        self._conn.execute(
            "UPDATE procedural_memory SET success_count = success_count + %s, "
            "failure_count = failure_count + %s, last_used_at = now(), "
            "retrieval_score = 1.0, updated_at = now() WHERE id = %s",
            (1 if success else 0, 0 if success else 1, procedure_id),
        )

    def decay(self, org_id: str, *, halflife_days: float | None = None) -> int:
        halflife = halflife_days or self._settings.memory_decay_halflife_days
        rows = self._conn.execute(
            "UPDATE procedural_memory SET retrieval_score = "
            "pow(0.5::FLOAT8, (EXTRACT(EPOCH FROM (now() - COALESCE(last_used_at, created_at))) "
            "/ 86400.0) / %s), updated_at = now() WHERE org_id = %s RETURNING id",
            (halflife, org_id),
        ).fetchall()
        return len(rows)
