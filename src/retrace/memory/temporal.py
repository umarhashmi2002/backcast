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
from uuid import UUID

from ..db.connection import Connection
from .models import Belief, BeliefState, Evidence

_HLC_RE = re.compile(r"^\d+(\.\d+)?$")

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
