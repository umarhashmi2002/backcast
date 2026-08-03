"""Temporal belief reconstruction via CockroachDB ``AS OF SYSTEM TIME``.

Given an HLC captured when the agent formed a belief, reconstruct the exact,
transactionally-consistent state the database held at that instant. Evidence and
beliefs written *after* that HLC are invisible — the no-leak guarantee is
enforced by MVCC, not by application filtering.

The HLC and incident id are validated and inlined because ``AS OF SYSTEM TIME``
requires a constant timestamp expression (no bind placeholder).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from ..db.connection import Connection, parse_vector
from .models import Belief, BeliefState, Evidence, RecalledEvidence
from .scoring import cosine_similarity

_HLC_RE = re.compile(r"^\d+(\.\d+)?$")
_ORG_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

_BELIEF_COLS = (
    "id, org_id, incident_id, hypothesis_id, confidence, rationale, valid_from, "
    "incident_state_version, model_id, prompt_version, created_by, db_ts::STRING AS db_ts"
)
_EVIDENCE_COLS = (
    "id, org_id, incident_id, kind, source, content, observed_at, s3_uri, "
    "db_ts::STRING AS db_ts, created_at"
)


class TemporalReconstructor:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def capture_hlc(self) -> str:
        """Return the current cluster HLC as a decimal string."""
        row = self._conn.execute("SELECT cluster_logical_timestamp()::STRING AS ts").fetchone()
        assert row is not None
        return str(row["ts"])

    def reconstruct(self, incident_id: UUID | str, as_of_hlc: str) -> BeliefState:
        """Reconstruct the agent's beliefs and available evidence at ``as_of_hlc``."""
        if not _HLC_RE.match(as_of_hlc):
            raise ValueError(f"Invalid HLC timestamp: {as_of_hlc!r}")
        iid = str(UUID(str(incident_id)))  # validate to prevent injection when inlined

        belief_rows = self._conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs AS OF SYSTEM TIME '{as_of_hlc}' "
            f"WHERE incident_id = '{iid}' AND valid_until IS NULL ORDER BY confidence DESC"
        ).fetchall()
        evidence_rows = self._conn.execute(
            f"SELECT {_EVIDENCE_COLS} FROM evidence AS OF SYSTEM TIME '{as_of_hlc}' "
            f"WHERE incident_id = '{iid}' ORDER BY observed_at"
        ).fetchall()

        return BeliefState(
            incident_id=UUID(iid),
            as_of_hlc=as_of_hlc,
            beliefs=[Belief(**row) for row in belief_rows],
            evidence=[Evidence(**row) for row in evidence_rows],
        )

    def historical_recall(
        self,
        org_id: str,
        query_embedding: Sequence[float],
        as_of_hlc: str,
        *,
        top_k: int = 8,
        exclude_incident: UUID | str | None = None,
    ) -> list[RecalledEvidence]:
        """Recall evidence as it existed at ``as_of_hlc`` — exact distance, no ANN.

        The C-SPANN ANN index is not guaranteed to accelerate historical
        (``AS OF SYSTEM TIME``) reads, so this reconstructs the bounded, tenant-
        scoped set at that HLC and ranks it by *exact* cosine similarity. Evidence
        written after ``as_of_hlc`` is invisible (MVCC), so there is no future leak.
        """
        if not _HLC_RE.match(as_of_hlc):
            raise ValueError(f"Invalid HLC timestamp: {as_of_hlc!r}")
        if not _ORG_RE.match(org_id):
            raise ValueError(f"Unsafe org id for inlining: {org_id!r}")

        where = f"org_id = '{org_id}' AND embedding IS NOT NULL"
        if exclude_incident is not None:
            where += f" AND incident_id <> '{UUID(str(exclude_incident))}'"

        rows = self._conn.execute(
            "SELECT id, incident_id, kind, content, observed_at, embedding::STRING AS emb "
            f"FROM evidence AS OF SYSTEM TIME '{as_of_hlc}' WHERE {where}"
        ).fetchall()

        recalled = [
            RecalledEvidence(
                id=row["id"],
                incident_id=row["incident_id"],
                kind=row["kind"],
                content=row["content"],
                observed_at=row["observed_at"],
                distance=round(1.0 - cosine_similarity(query_embedding, parse_vector(row["emb"])), 4),
                score=round(cosine_similarity(query_embedding, parse_vector(row["emb"])), 4),
            )
            for row in rows
        ]
        recalled.sort(key=lambda r: r.score, reverse=True)
        return recalled[:top_k]
