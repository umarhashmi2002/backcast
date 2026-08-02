"""Immutable evidence store (episodic memory) with C-SPANN vector recall."""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Json

from ..config import Settings, get_settings
from ..db.connection import Connection, vector_literal
from .embeddings import Embedder
from .models import Evidence, RecalledEvidence
from .scoring import evidence_score

_INSERT = """
INSERT INTO evidence (org_id, incident_id, kind, source, content, embedding, observed_at, s3_uri, metadata)
VALUES (%s, %s, %s, %s, %s, %s::VECTOR, COALESCE(%s::TIMESTAMPTZ, now()), %s, %s)
RETURNING id, db_ts::STRING AS db_ts, observed_at, created_at
"""


class EvidenceStore:
    """Records evidence (never updated/deleted) and recalls it semantically."""

    def __init__(
        self, conn: Connection, embedder: Embedder, settings: Settings | None = None
    ) -> None:
        self._conn = conn
        self._embedder = embedder
        self._settings = settings or get_settings()

    def record(self, evidence: Evidence, *, embed: bool = True) -> Evidence:
        vector = vector_literal(self._embedder.embed_one(evidence.content)) if embed else None
        row = self._conn.execute(
            _INSERT,
            (
                evidence.org_id,
                evidence.incident_id,
                evidence.kind.value,
                evidence.source,
                evidence.content,
                vector,
                evidence.observed_at,
                evidence.s3_uri,
                Json(evidence.metadata),
            ),
        ).fetchone()
        assert row is not None
        evidence.id = row["id"]
        evidence.db_ts = row["db_ts"]
        evidence.observed_at = row["observed_at"]
        evidence.created_at = row["created_at"]
        return evidence

    def recall(
        self,
        org_id: str,
        query: str,
        *,
        top_k: int | None = None,
        exclude_incident: UUID | str | None = None,
    ) -> list[RecalledEvidence]:
        """Return the most relevant past evidence by vector similarity + recency."""
        k = top_k or self._settings.recall_top_k
        query_vector = vector_literal(self._embedder.embed_one(query))
        sql = (
            "SELECT id, incident_id, kind, content, observed_at, "
            "embedding <-> %s::VECTOR AS distance "
            "FROM evidence WHERE org_id = %s AND embedding IS NOT NULL"
        )
        params: list[object] = [query_vector, org_id]
        if exclude_incident is not None:
            sql += " AND incident_id <> %s"
            params.append(exclude_incident)
        sql += " ORDER BY distance LIMIT %s"
        params.append(k * 3)  # over-fetch, then re-rank by blended score

        rows = self._conn.execute(sql, params).fetchall()
        halflife = self._settings.memory_decay_halflife_days
        recalled = [
            RecalledEvidence(
                id=row["id"],
                incident_id=row["incident_id"],
                kind=row["kind"],
                content=row["content"],
                observed_at=row["observed_at"],
                distance=float(row["distance"]),
                score=evidence_score(float(row["distance"]), row["observed_at"], halflife),
            )
            for row in rows
        ]
        recalled.sort(key=lambda r: r.score, reverse=True)
        return recalled[:k]

    def for_incident(self, incident_id: UUID | str) -> list[Evidence]:
        """Return all evidence rows for an incident (immutable, ordered by time)."""
        rows = self._conn.execute(
            "SELECT id, org_id, incident_id, kind, source, content, observed_at, s3_uri, "
            "db_ts::STRING AS db_ts, created_at "
            "FROM evidence WHERE incident_id = %s ORDER BY observed_at",
            (incident_id,),
        ).fetchall()
        return [Evidence(**row) for row in rows]
