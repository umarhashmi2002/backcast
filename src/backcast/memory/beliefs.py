"""Hypotheses, time-versioned beliefs, and the typed provenance graph."""

from __future__ import annotations

from uuid import UUID

from ..db.connection import Connection
from .models import Belief, Hypothesis, HypothesisStatus, NodeType, Relation


class BeliefStore:
    """Manages the agent's evolving beliefs and why it holds them."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # --- hypotheses --------------------------------------------------------
    def create_hypothesis(self, org_id: str, incident_id: UUID | str, statement: str) -> Hypothesis:
        row = self._conn.execute(
            "INSERT INTO hypotheses (org_id, incident_id, statement) VALUES (%s, %s, %s) "
            "RETURNING id, db_ts::STRING AS db_ts, created_at",
            (org_id, incident_id, statement),
        ).fetchone()
        assert row is not None
        return Hypothesis(
            id=row["id"],
            org_id=org_id,
            incident_id=UUID(str(incident_id)),
            statement=statement,
            db_ts=row["db_ts"],
            created_at=row["created_at"],
        )

    def get_or_create_hypothesis(
        self, org_id: str, incident_id: UUID | str, statement: str
    ) -> Hypothesis:
        """Return the incident's hypothesis with this statement, creating it if new."""
        row = self._conn.execute(
            "SELECT id, status, db_ts::STRING AS db_ts, created_at FROM hypotheses "
            "WHERE incident_id = %s AND statement = %s LIMIT 1",
            (incident_id, statement),
        ).fetchone()
        if row is not None:
            return Hypothesis(
                id=row["id"],
                org_id=org_id,
                incident_id=UUID(str(incident_id)),
                statement=statement,
                status=row["status"],
                db_ts=row["db_ts"],
                created_at=row["created_at"],
            )
        return self.create_hypothesis(org_id, incident_id, statement)

    def set_hypothesis_status(self, hypothesis_id: UUID | str, status: HypothesisStatus) -> None:
        self._conn.execute(
            "UPDATE hypotheses SET status = %s, updated_at = now() WHERE id = %s",
            (status.value, hypothesis_id),
        )

    # --- beliefs (append-only, bitemporal) ---------------------------------
    def set_belief(
        self,
        org_id: str,
        incident_id: UUID | str,
        hypothesis_id: UUID | str,
        confidence: float,
        *,
        rationale: str | None = None,
        model_id: str | None = None,
        prompt_version: str | None = None,
        incident_state_version: int | None = None,
        created_by: str = "agent",
    ) -> Belief:
        """Record a new belief, closing (superseding) the prior current one."""
        with self._conn.transaction():
            row = self._conn.execute(
                "INSERT INTO beliefs (org_id, incident_id, hypothesis_id, confidence, rationale, "
                "model_id, prompt_version, incident_state_version, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, valid_from, db_ts::STRING AS db_ts",
                (
                    org_id,
                    incident_id,
                    hypothesis_id,
                    confidence,
                    rationale,
                    model_id,
                    prompt_version,
                    incident_state_version,
                    created_by,
                ),
            ).fetchone()
            assert row is not None
            new_id = row["id"]
            superseded = self._conn.execute(
                "UPDATE beliefs SET valid_until = now(), superseded_by = %s "
                "WHERE incident_id = %s AND hypothesis_id = %s AND valid_until IS NULL AND id <> %s "
                "RETURNING id",
                (new_id, incident_id, hypothesis_id, new_id),
            ).fetchall()
            for prev in superseded:
                self._add_edge_in_txn(
                    org_id,
                    incident_id,
                    NodeType.belief,
                    new_id,
                    Relation.supersedes,
                    NodeType.belief,
                    prev["id"],
                )
        return Belief(
            id=new_id,
            org_id=org_id,
            incident_id=UUID(str(incident_id)),
            hypothesis_id=UUID(str(hypothesis_id)),
            confidence=confidence,
            rationale=rationale,
            valid_from=row["valid_from"],
            model_id=model_id,
            prompt_version=prompt_version,
            incident_state_version=incident_state_version,
            created_by=created_by,
            db_ts=row["db_ts"],
        )

    def current_beliefs(self, incident_id: UUID | str) -> list[Belief]:
        rows = self._conn.execute(
            "SELECT id, org_id, incident_id, hypothesis_id, confidence, rationale, valid_from, "
            "incident_state_version, model_id, prompt_version, created_by, db_ts::STRING AS db_ts "
            "FROM beliefs WHERE incident_id = %s AND valid_until IS NULL "
            "ORDER BY confidence DESC",
            (incident_id,),
        ).fetchall()
        return [Belief(**row) for row in rows]

    def belief_history(self, incident_id: UUID | str, hypothesis_id: UUID | str) -> list[Belief]:
        rows = self._conn.execute(
            "SELECT id, org_id, incident_id, hypothesis_id, confidence, rationale, valid_from, "
            "valid_until, superseded_by, incident_state_version, model_id, prompt_version, "
            "created_by, db_ts::STRING AS db_ts "
            "FROM beliefs WHERE incident_id = %s AND hypothesis_id = %s ORDER BY valid_from",
            (incident_id, hypothesis_id),
        ).fetchall()
        return [Belief(**row) for row in rows]

    # --- provenance edges --------------------------------------------------
    def add_edge(
        self,
        org_id: str,
        incident_id: UUID | str | None,
        src_type: NodeType,
        src_id: UUID | str,
        relation: Relation,
        dst_type: NodeType,
        dst_id: UUID | str,
        *,
        weight: float = 1.0,
        note: str | None = None,
    ) -> None:
        self._add_edge_in_txn(
            org_id,
            incident_id,
            src_type,
            src_id,
            relation,
            dst_type,
            dst_id,
            weight=weight,
            note=note,
        )

    def _add_edge_in_txn(
        self,
        org_id: str,
        incident_id: UUID | str | None,
        src_type: NodeType,
        src_id: UUID | str,
        relation: Relation,
        dst_type: NodeType,
        dst_id: UUID | str,
        *,
        weight: float = 1.0,
        note: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO provenance_edges "
            "(org_id, incident_id, src_type, src_id, relation, dst_type, dst_id, weight, note) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                org_id,
                incident_id,
                src_type.value,
                src_id,
                relation.value,
                dst_type.value,
                dst_id,
                weight,
                note,
            ),
        )
